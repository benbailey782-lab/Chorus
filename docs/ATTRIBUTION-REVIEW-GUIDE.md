# Attribution Review Guide

**Status:** shipped in Phase 4.

Phase 4 of Chorus adds per-chapter speaker attribution: every narrative chapter is split into ordered segments, each segment tagged with a `render_mode` and (where applicable) a `character_id`. Attribution runs via the file-drop LLM workflow (see `docs/FILE-DROP-WORKFLOW.md`). The operator-facing review UI ships at `/project/:idOrSlug/chapters/:chapterId` and covers prose + table views, filter drawer, detail-panel inline editing, and bulk operations. The Casting page now also surfaces a Chapters section with per-chapter status and an "Attribute all" project-level action. This guide documents both the shipped UI and the underlying HTTP surface (still intact for `curl`-based inspection).

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

## Review UI (shipped)

Live at `/project/:idOrSlug/chapters/:chapterId` → `ChapterReview.tsx`. Two-pane desktop layout (prose/table on the left, detail panel on the right); the detail panel becomes a bottom-sheet on mobile. Confidence thresholds are single-sourced from `frontend/src/lib/constants.ts::CONFIDENCE` (green ≥85, yellow 70–84, red <70, neutral for null). View-mode preference persists in localStorage under `review:view-mode`.

### Prose view (default)

Chapter text rendered top-to-bottom with per-segment styling by `render_mode` (prose, dialogue, epigraph, letter, poetry, song_lyrics, emphasis, thought, chapter_heading). Confidence surfaces as a left-border tint on each segment. Attributed speakers show as float labels above dialogue/thought/letter segments. Click-to-select opens the detail panel. Keyboard: `j`/`k` or `↑`/`↓` to navigate, `Enter` to open detail, `Esc` to clear selection, `?` for the help overlay.

### Table view

Tabular list with sortable columns, confidence-tinted cells (same CONFIDENCE band), checkbox multi-select with an indeterminate header checkbox, and per-row `content-visibility:auto` so long chapters stay scroll-smooth.

### Filters

Drawer on desktop, bottom-sheet on mobile:
- Speaker multi-select (includes an "Unattributed" bucket)
- Confidence dual-range slider
- Render mode multi-select
- "Has emotion tags" toggle
- "Has notes" toggle

Persisted per-chapter in localStorage under `review:filters:{chapterId}`. Helpers live in `frontend/src/lib/review-filters.ts`.

### Detail panel

Opened from either view. Editable fields: `text` (textarea), `speaker` (character dropdown, voice-library-aware), `render_mode` (dropdown), `emotion_tags` (chips with add/remove), `notes`. Confidence is read-only. Save triggers `PATCH /api/segments/{id}`; `Cmd/Ctrl+Enter` saves from anywhere in the panel. When the text value differs from the stored one, the backend flips `segments.text_modified=1` and the UI surfaces a "✎ Edited" marker on that segment in both views.

### Bulk operations

Table view exposes multi-select (including `Cmd/Ctrl+A` select-all of the current filtered set):
- **Reassign speaker** — single call to `POST /api/segments/bulk-reassign`
- **Set render mode** — single call to `POST /api/segments/bulk-reassign`
- **Add emotion tags / Remove emotion tags** — per-segment PATCHes, because the bulk endpoint applies the same `changes` to every selected segment and would overwrite per-segment tag lists.

### Casting page integration

The project's Casting page gained a Chapters section (`frontend/src/components/casting/ChaptersSection.tsx`):
- Progress bar `{attributed} of {total} chapters attributed`
- Per-chapter status chip: `Not started` / `Attributing…` (warn, pulse) / `Attributed` (accent) / `Failed` (error)
- Inline row actions: `Attribute` for unattributed, `Retry` for failed, `Review` for attributed
- `Attribute all ({n} remaining)` project-level button that disables while any `attribute_chapter` job is active

---

## Deferred to later phases

- **"Approve 90+" bulk action** — Phase 5. Requires TTS generation to have anything to approve for; the surface is a no-op until Voicebox.
- **Audio preview per segment** — Phase 5. `GET /api/segments/{id}/preview` returns HTTP 501 until Voicebox is wired; the UI button is present but disabled.
- **Smart merge on re-attribution** — Phase 7. Re-attribution currently wipes all segments including user edits (`text_modified=1` rows). **Warning**: run re-attribution only when you want to discard operator edits. A segment-level diff/merge strategy is scoped for Phase 7.
- **Pronunciation override UI** — Phase 5, paired with TTS so changes can be validated against generated audio.
