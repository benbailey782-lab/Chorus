# Attribution Review Guide

**Status:** backend-ready; UI landing next session.

Phase 4 of Chorus adds per-chapter speaker attribution: every narrative chapter is split into ordered segments, each segment tagged with a `render_mode` and (where applicable) a `character_id`. Attribution runs via the file-drop LLM workflow (see `docs/FILE-DROP-WORKFLOW.md`); review is currently API-only while the UI is built out. This guide documents the available HTTP surface and the segment data model so operators can inspect, edit, and sanity-check attribution output via `curl` until the review UI ships.

## Segment data model

Each row in the `segments` table represents a single contiguous span of source text inside one chapter:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Stable segment identifier. |
| `chapter_id` | UUID (FK → `chapters.id`) | Parent chapter. |
| `order_index` | int | 0-based position within chapter. Unique per chapter. |
| `text` | text | Verbatim source substring. |
| `render_mode` | enum (9 values, see below) | How the renderer should treat this span. |
| `character_id` | UUID? (FK → `characters.id`, `ON DELETE SET NULL`) | Null for non-dialogue modes. |
| `confidence` | float 0–100 | LLM-reported confidence for this segment's attribution. |
| `notes` | text? | LLM-provided rationale or operator note. |

### `render_mode` vocabulary (§6, all 9 values)

1. `narration` — third-person narrator; spoken by the narrator voice.
2. `dialogue` — in-world speech by a named character. Requires `character_id`.
3. `internal_monologue` — character's inner thought. Requires `character_id`.
4. `letter` — read letter, in-world correspondence. Requires `character_id` (sender).
5. `song` — lyric, verse, or chant. `character_id` optional.
6. `chant` — ritual or group utterance. `character_id` optional.
7. `prophecy` — oracle, vision, or dream-speech. `character_id` optional.
8. `untranslated` — foreign language or proper-noun-only line rendered raw. `character_id` optional.
9. `skip` — structural content the renderer should omit (headings, epigraphs, editorial notes). `character_id` must be null.

The SQLite CHECK constraint enforces this set exactly — attempted inserts with other values fail at the DB layer.

## Running attribution

Attribution is a file-drop job: the backend writes a prompt to `data/llm_queue/pending/`, a companion Claude Code session processes it, and the jobs worker ingests the response. Trigger endpoints:

### Attribute a single chapter

```bash
curl -X POST http://localhost:8765/api/chapters/<chapter_id>/attribute
```

Response:
```json
{ "chapter_id": "…", "job_id": "…", "status": "awaiting_response" }
```

The returned `job_id` is pollable via `GET /api/jobs/{job_id}`. On ingest, the project transitions `casting → attributing` on the first chapter and `attributing → attributed` once every chapter has ≥1 segment.

### Attribute every remaining chapter in a project

```bash
curl -X POST http://localhost:8765/api/projects/<id_or_slug>/attribute-all
```

Skips chapters that already have segments. Returns a list of `{chapter_id, job_id}` pairs plus a `skipped` count.

## Reviewing segments

### List all segments for a chapter

```bash
curl http://localhost:8765/api/chapters/<chapter_id>/segments
```

Returns segments ordered by `order_index` with the full data model above.

### Edit a single segment (reassign character, change render_mode, tweak text)

```bash
curl -X PATCH http://localhost:8765/api/segments/<segment_id> \
  -H 'Content-Type: application/json' \
  -d '{"character_id": "<uuid>", "render_mode": "dialogue", "notes": "overridden by operator"}'
```

Any subset of `{text, render_mode, character_id, confidence, notes}` may be sent. Validation: `render_mode=skip` forces `character_id=null`; dialogue/internal_monologue/letter require a non-null `character_id`.

### Bulk reassign (fix a whole character at once)

```bash
curl -X POST http://localhost:8765/api/segments/bulk-reassign \
  -H 'Content-Type: application/json' \
  -d '{"segment_ids": ["id1","id2","id3"], "character_id": "<uuid>"}'
```

All listed segments are reassigned atomically. Returns `{updated_count, failed_ids}`.

### Preview rendered audio for one segment

```bash
curl http://localhost:8765/api/segments/<segment_id>/preview
```

Currently returns HTTP **501 Not Implemented** — this is expected pending Voicebox wiring. The endpoint is in place so the UI can wire the button now.

## Sanity-check recipe

After running attribution on a chapter, from any shell:

```bash
# How many segments, and what render_mode distribution?
curl -s http://localhost:8765/api/chapters/<id>/segments | jq '[.[] | .render_mode] | group_by(.) | map({mode: .[0], count: length})'

# Which characters are speaking, and how many lines each?
curl -s http://localhost:8765/api/chapters/<id>/segments | jq '[.[] | select(.character_id != null) | .character_id] | group_by(.) | map({character_id: .[0], lines: length})'

# Mean confidence (a low number = spot-check candidate)
curl -s http://localhost:8765/api/chapters/<id>/segments | jq '[.[].confidence] | add / length'
```

The AGoT BRAN round-trip benchmark: 217 segments, mean confidence 96.9.

---

## Review UI — coming in next session

The screens below are planned for P5–P8. Backend already supports every operation they need.

### Prose view (P5)
Chapter text rendered top-to-bottom with per-segment coloring by speaker. Click a segment → detail panel opens. Narration and skip segments visually de-emphasized. Segment confidence surfaced as a subtle left-border tint (red → green).

### Table view (P6)
Tabular list of segments with columns `#, text (truncated), render_mode, character, confidence, notes`. Filterable by character, render_mode, confidence range. Sortable. Multi-select for bulk ops.

### Detail panel (P7)
Right-side drawer opened from either view. Shows full segment text, character dropdown (voice-library-aware), render_mode dropdown, notes field, confidence read-only, `Preview audio` button (will unblock once the 501 endpoint becomes 200), `Save` and `Revert` buttons. Inline edits persist via `PATCH /api/segments/{id}`.

### Bulk operations (P8)
Reassign N segments to one character; change render_mode across a selection; mark a span `skip`. All go through `POST /api/segments/bulk-reassign` and the single-segment PATCH.

### Keyboard shortcuts (P8)
- `j` / `k` — next / previous segment.
- `c` — open character picker for current segment.
- `r` — open render_mode picker.
- `s` — toggle `skip`.
- `/` — focus filter input (table view).
- `?` — show shortcut cheatsheet.

See `scratch/instructions.txt` for the Phase 4 resume marker.
