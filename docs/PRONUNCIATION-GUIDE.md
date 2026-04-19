# Pronunciation Overrides — User Guide

Pronunciations let you force specific spellings through a text-substitution
pass that runs **before** TTS. Voicebox (and any downstream TTS) sees the
respelled form — not the original — so the correct pronunciation is
deterministic rather than at the mercy of the engine's best guess.

## What pronunciations do

- **Term → phonetic text substitution.** `Cersei` → `SUR-see`,
  `Dothraki` → `doe-THRAH-kee`.
- Applied case-insensitively with word-boundary regex. `Cersei's` still
  matches `Cersei`.
- **Longest-term-first.** When both `Varys` and `Lord Varys` exist, `Lord Varys`
  is tried first so its phonetic wins.
- Pure text swap. Voicebox never sees an IPA string or SSML — Chorus rewrites
  the segment text and hands the rewritten string to TTS. The `phonetic` field
  is the canonical form; pick the respelling you want the engine to hear.

Implementation: `backend/nlp/merge_pronunciations.py` does the regex build and
the merge across scopes.

## Scopes

Chorus has two scopes:

- **Global** (`pronunciations_global`) — applies to every project. Good for
  names that occur across a series, or common loanwords.
- **Project** (`pronunciations`) — scoped to one project. **Overrides global**
  for any term that matches by lowercase string.

When the generation pipeline assembles the substitution list for a chapter, it
merges global ∪ project with project winning on collisions. Character-level
scoping (`applies_to_character_id`) is **deferred to Phase 7** — same term
pronounced differently by different speakers.

## Managing pronunciations

Two UI surfaces, both backed by the same
`frontend/src/components/pronunciations/PronunciationManager.tsx` component
parameterized by scope:

- **Global:** `/settings/pronunciations`
- **Project:** `/project/<idOrSlug>/pronunciations`

### Extracting from a book (Pass 3)

Uses the file-drop LLM workflow (§12A). Cheap and reviewable.

1. Open `/project/<idOrSlug>/pronunciations`.
2. Click **Extract from book**. Confirm the modal.
3. Chorus writes `data/llm_queue/pending/request_<id>.md` using the
   `pronounce_unusual.md` prompt. The project-level job enters
   `awaiting_response`.
4. Your companion Claude Code session (see `docs/FILE-DROP-WORKFLOW.md`)
   processes the request and writes `data/llm_queue/responses/response_<id>.json`.
5. The worker ingests the response. The handler maps `word` → `term` and
   `respelling` → `phonetic` (the response schema uses the LLM-friendly
   field names; Chorus normalizes to the DB names). New rows are inserted with
   `source = "pass3"`.
6. Harness-validated baseline on *A Game of Thrones* book 1: ~73 entries
   extracted; 62 at 90+ confidence.

### Manual entry

- Inline add via the manager UI. `term` (what appears in the book) and
  `phonetic` (what Voicebox should pronounce). Confidence defaults to 100 for
  manual entries.
- Inline edit on any row. Delete via the row action.

### Promote project → global

Any project-scoped entry has a **Promote to global** action. Useful when an
entry (e.g., a respelling for "Varys") is stable enough that you want it to
apply to all future projects without re-extracting.

### Import / Export JSON

- **Export** — dumps the visible scope to a JSON file.
- **Import** — accepts the same JSON shape; de-dupes by lowercase `term`.
  Useful for sharing libraries across Chorus installations, or for
  version-controlling the "canonical" pronunciations for a series.

## Merge precedence at generation time

Documented in `backend/nlp/merge_pronunciations.py`:

1. Build the candidate list: `global_rows` + `project_rows`.
2. De-dupe by `term.lower()` with **project winning** on collision.
3. Sort by `len(term) DESC` so longer terms match first.
4. Build one compiled regex per entry with `\b…\b` boundaries and `re.IGNORECASE`.
5. Apply all substitutions to the segment text before sending to TTS.

## Deferred

- **Per-character scoping** (`applies_to_character_id` column is reserved in
  the schema). Use case: one term pronounced differently by different
  characters. Phase 7.
- **IPA / SSML emission.** Current design is pure text rewrite. A future
  engine-aware path could emit SSML where supported.
