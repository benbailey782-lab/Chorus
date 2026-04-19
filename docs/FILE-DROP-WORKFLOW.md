# File-Drop LLM Workflow (§12A)

Chorus doesn't call the Anthropic API directly. Instead, when a Claude-driven
pass kicks off, it writes the rendered prompt to disk and waits for a
companion Claude Code session to drop the response back.

This is the only LLM transport in v1. A future `LLM_MODE=api` flag would swap
in a direct SDK path (see `docs/VOICEBOX-WIRING.md` pattern), but it's not
implemented yet.

## Directory layout

```
data/llm_queue/
├── pending/      # Chorus writes here  →  request_<job-id>.md
├── responses/    # Claude Code writes  →  response_<job-id>.json
└── completed/    # Chorus moves the request here after ingestion
```

## What Chorus writes

Each `request_<job-id>.md` has a small YAML front-matter block followed by
the fully-rendered prompt — the same text Claude would receive via the API:

```markdown
---
book_text_chars: 47
created_at: 2026-04-18T18:15:00+00:00
id: e765ae4f-823d-41b0-ab50-75f71fc49bad
kind: extract_characters
project_id: p_demo
project_slug: demo
---

# Cast Extraction Prompt
…
```

The `id` in the front matter is the job id; response files must use the
same id in their filename: `response_<job-id>.json`.

## Running the companion Claude Code session

Open a second terminal in the Chorus repo root and paste this as a standing
instruction to Claude Code:

> Watch `data/llm_queue/pending/` for new `request_*.md` files. For each:
>
> 1. Read the request file. The `id` in its YAML front matter is the job id.
> 2. Execute the prompt that follows the front-matter block. It will ask you
>    to return a specific JSON shape (see the prompt's "Output Schema"
>    section).
> 3. Write the resulting JSON — and ONLY the JSON, no prose, no code fences —
>    to `data/llm_queue/responses/response_<job-id>.json`, where `<job-id>`
>    matches the id from the request's front matter.
> 4. After writing the response, move the request file from
>    `data/llm_queue/pending/` to `data/llm_queue/completed/`.

> **Cadence recommendation (Phase 4):** poll `data/llm_queue/pending/` about
> every **3 seconds**. Chorus's own worker ticks every 1 second now, so a 3s
> companion cadence keeps the round-trip under ~4s end-to-end without pegging
> either side on filesystem watching.

Chorus's background worker polls `responses/` every 1 second. When it sees
a `response_<job-id>.json` that matches a job in `awaiting_response` state,
it parses the JSON, validates it, writes the results to the database, marks
the job `complete`, moves the request file to `completed/`, and deletes the
response file.

## What Chorus does on the hot path

1. `submit_request(request_id, prompt_text, metadata)` writes
   `pending/request_<id>.md` atomically. The matching job row is marked
   `awaiting_response`.
2. A `poll_for_response` tick reads `responses/response_<id>.json`. If the
   file is malformed, the job is marked `failed` with the parse error so you
   can fix the response file and re-drop it (no need to rerun the prompt).
3. On successful ingestion:
   - `mark_completed(id)` moves `pending/request_<id>.md` → `completed/`.
   - `delete_response(id)` removes the response file.
   - The job row transitions to `complete` with a result summary.

## What to do when something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Job stuck in `awaiting_response` forever | Companion session isn't running, or hasn't noticed the new file. | Re-paste the standing instruction to your Claude Code session. |
| Job goes to `failed` immediately with a JSON parse error | Response file isn't valid JSON (usually from prose leaking around the array). | Edit `data/llm_queue/responses/response_<id>.json` to be just the JSON array and re-drop it; the worker picks it up on the next tick. |
| Job goes to `failed` with a validation error | Response JSON is valid but missing required fields or references an unknown `voice_id`. | Fix the response file. You can keep the request file in `pending/` — it won't be re-submitted, but it's useful for re-reading. |
| Multiple requests stacked up | Operator was AFK. | The companion session processes them one at a time in order. |
| Response file left behind after a rename | Chorus failed to `unlink` it after ingestion (rare). | Safe to delete manually. |

## Inspecting the queue

From inside the project root:

```bash
ls data/llm_queue/pending/      # outstanding requests
ls data/llm_queue/responses/    # responses Chorus hasn't ingested yet
ls data/llm_queue/completed/    # historical prompts (audit trail)
```

All three dirs are `.gitignore`d. Keep `completed/` around — it's the
file-level audit trail for every LLM exchange the project has ever had.

## Re-ingesting after the Phase 4 chapter-split fix

Any project that was ingested **before** the Phase 4 chapter-splitting fix
may have false-positive chapter breaks — the old detector treated a bare
`I` on its own line (italicized emphasis flattened by the EPUB parser) as a
Roman-numeral chapter heading. After Phase 4, the detector only accepts a
bare Roman-numeral line as a heading when it has empty-string lines on both
sides and the doc-wide count of candidates is reasonable.

If `chapter_count` on an existing project is noticeably higher than the
book's real chapter count, delete the project and re-upload the source.

## Handler registry

Current file-drop handlers (registered via `@register_handler(kind)` in
`backend/jobs/worker.py`):

| Kind | Module | Prompt |
|---|---|---|
| `extract_characters` | `backend/nlp/extract_characters.py` | `extract_cast.md` |
| `auto_cast`          | `backend/nlp/auto_cast.py`          | `auto_cast_voices.md` |

Phase 4 will add `attribute_chapter`; Phase 3 stops here.
