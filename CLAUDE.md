# Chorus — Multi-Voice Theatrical Audiobook Generator

## Project at a glance

- **Spec:** `CHORUS-SPEC.md` — authoritative. Update this file when scope shifts.
- **Backend:** Python 3.11+, FastAPI, SQLite (`backend/`).
- **Frontend:** React 18 + Vite + TypeScript + Tailwind + Zustand + TanStack Query (`frontend/`).
- **LLM:** Anthropic SDK. Opus 4.7 for cast extraction + low-confidence attribution. Sonnet 4.6 for bulk per-chapter work.
- **TTS:** Voicebox REST API (expected at `VOICEBOX_BASE_URL`, default `http://localhost:5173` on Mac).
- **Deploy model:** Mac runs backend; phone connects via `http://chorus.local:8765` as a PWA.

## Current status

- Phase 0 (Foundation) — scaffolded.
- Phase 1 (Ingestion + Library) — TXT + EPUB ingestion, naive chapter detection, Library + Project views. Claude chapter-detection fallback not yet wired.
- Phase 2 (Voice Library) — **done in Voicebox-stub mode** (dev is on Windows, no Voicebox installed). Full CRUD + metadata + optional reference-audio upload + mobile-first dark UI at §15.8 tokens. Voicebox wiring punch-list: `docs/VOICEBOX-WIRING.md`.
- Phase 3 (Cast Extraction + Auto-Casting) — **done via file-drop LLM integration (§12A)**. No Anthropic SDK calls; prompts written to `data/llm_queue/pending/`, responses read from `data/llm_queue/responses/`. Jobs worker reconciles them. Operator playbook: `docs/FILE-DROP-WORKFLOW.md`.
- Phase 4 (Per-Chapter Attribution) — **backend + API complete** (schema v4, `attribute_chapter` handler, `POST /api/chapters/{id}/attribute`, `POST /api/projects/{id}/attribute-all`, `GET /api/chapters/{id}/segments`, `PATCH /api/segments/{id}`, `POST /api/segments/bulk-reassign`, `GET /api/segments/{id}/preview` → 501). **Review UI deferred** — resume at P5 (prose view) next session; see `scratch/instructions.txt` for the resume marker. Round-trip validated against AGoT BRAN via file-drop: 217 segments, mean confidence 96.9, project → `attributed`.
- Later phases per spec §17.

## Conventions

- NLP prompts live in `backend/nlp/prompts/*.md` — edit those files, do not inline prompts in Python.
- SQLite schema in `backend/db.py` (single canonical `SCHEMA_SQL`). When you change the schema, bump `SCHEMA_VERSION` and add a migration in `_run_migrations` rather than mutating `SCHEMA_SQL` in place. Destructive migrations must abort with `MigrationAborted` if the affected table has rows.
- FastAPI binds `0.0.0.0:8765` so the phone can reach it on LAN.
- Vite dev server binds `0.0.0.0:5173` and proxies `/api` → backend `:8765`.
- IDs: UUIDv4 strings. Slugs: lowercase kebab, unique per project. Voice ids: `v_<slug>_<hex6>`.
- Design tokens: §15.8 (dark palette, Chorus teal `#4EC8BE`). Never use the retired Phase-1 `ink`/`parchment` tokens.
- Reusable Tailwind component classes live in `frontend/src/index.css` (`btn-primary`, `btn-surface`, `btn-ghost`, `btn-danger`, `input`, `card`, `chip`). Prefer these over ad-hoc utility clusters.
- Mobile tap targets must be ≥44px — use `min-h-tap`/`min-w-tap` or the `.btn*` classes which already include them.
- Voicebox: every TTS call-site goes through `backend/voices/voicebox_client.py`. Stubs raise `VoiceboxNotEnabled` when disabled; every endpoint has a `TODO(voicebox)` docstring with expected request/response shapes. Before wiring any real call, verify against Voicebox's `/docs` — §12.2 is tentative.
- Pydantic field names that collide with `ABCMeta` methods (e.g., `register`) must be aliased: Python name `register_` + `alias="register"` + `serialization_alias="register"` + `model_config = ConfigDict(populate_by_name=True)`. Call sites dump with `by_alias=True`.

## Running locally

```bash
# one-shot (Mac / Linux)
bash scripts/run.sh

# Windows
scripts\run.bat

# manual
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
(cd frontend && npm install && npm run dev -- --host 0.0.0.0)
```

Health check: `curl http://localhost:8765/api/health`.
From phone on same WiFi: `http://chorus.local:8765/api/health` (mDNS advertised).

## Verification scripts

- `python scripts/verify_anthropic.py` — confirms `ANTHROPIC_API_KEY` + basic call works.
- `python scripts/verify_voicebox.py` — confirms Voicebox is reachable (warns, doesn't fail, if absent).

## Things NOT to do

- Don't regenerate `CHORUS-SPEC.md` from scratch; treat it as durable.
- Don't hardcode prompts in Python. Use `backend/nlp/claude_client.load_prompt("name")`.
- Don't commit the `data/` directory or source EPUBs — covered by `.gitignore`.
- Don't assume `chorus.local` DNS exists for first-time callers; advertise mDNS via `backend/mdns.py` at startup.

## Phase-1 exit criterion

Drop the `A Game of Thrones` EPUB into a new project → see it parsed into ~73 chapters with correct titles.

## Phase-2 exit criterion (revised for Windows dev)

Add 5 voices via the UI with full §7.2 metadata (incl. optional reference-audio upload), confirm persistence across restarts, browse+filter on phone at 375px, edit and delete voices. No live Voicebox required. Upstream spec criterion ("preview plays from phone") is satisfied by streaming the stored reference audio; generated TTS preview arrives when Voicebox is wired (see `docs/VOICEBOX-WIRING.md`).

## Phase-3 exit criterion

Extract AGoT cast via file-drop LLM integration, auto-cast from voice library, manually inspect assignments are sensible.

### Phase-3 test recipe (Windows dev)

1. Start the backend + frontend (`scripts\run.bat`) and the companion Claude Code session (see `docs/FILE-DROP-WORKFLOW.md`).
2. Create a project and ingest a short EPUB or TXT via the Library tab.
3. Add at least one narrator-pool and one main-pool voice via the Voices tab.
4. Open the project → "Open casting" → "Extract Cast" → confirm the modal → the job should appear in `data/llm_queue/pending/request_<id>.md` and the companion session will respond.
5. Within seconds, the cast list populates; project status flips to `casting`.
6. Click "Run Auto-Cast" → a second request file lands; the companion session responds; each character card shows its assigned voice.
7. Click any character → pick a different voice from the right pane to verify manual override.

## Phase-4 exit criterion

Run attribution pass on AGoT book 1 chapter-by-chapter via file-drop; manually inspect a handful of chapters for quality; per-chapter review UI allows inline editing and bulk reassignment.

### Phase-4 backend conventions

- **`jobs.kind = "attribute_chapter"`** for per-chapter attribution jobs. Handler registered in `backend/nlp/attribute_chapter.py`; imported in `backend/main.py` so `@register_handler` fires before the worker starts.
- **File-drop worker poll is now 1s** (was 2s) — tightens round-trip latency. Companion Claude Code session cadence recommendation is 3s in `docs/FILE-DROP-WORKFLOW.md`.
- **Chapter-split regex** requires empty-string lines on both sides of a bare Roman-numeral heading; suppresses all bare-Romans when the doc has >100 such candidates; suppresses lone `I`/`V` when lowercase prose sits within 200 chars. Pre-Phase-4 projects with inflated `chapter_count` should be re-ingested (delete + re-upload source).
- **Segments schema**: v4 rebuild. `render_mode` CHECK enforces the full §6 nine-value vocabulary. `character_id` uses `ON DELETE SET NULL` so orphaned segments survive character deletion.
- **Project status transitions** on attribution:
  - `casting` → `attributing` when the first `attribute_chapter` job for the project hits `awaiting_response`
  - `attributing` → `attributed` when every chapter has at least one segment AND `chapter_count > 0`
- **`line_count` on characters** is recomputed after every successful attribute_chapter ingestion. The formula is "count of dialogue-mode segments assigned to this character across the whole project."

### Phase-3 conventions

- **Job `kind` vs spec's `type`**: the v1 DB schema used `kind`. We keep it for compatibility and map in-code vocabulary: `extract_characters`, `auto_cast`, `attribute_chapter` (Phase 4), etc. Spec §9.8 calls the column `type` — treat the two names as synonymous.
- **Handlers bind at import**: `backend/main.py` imports `extract_characters` and `auto_cast` so their `@register_handler` decorators fire before the worker starts. Any new handler added in a later phase must be imported in `main.py` too, or the worker will fail its job with "no handler registered".
- **Response retries are fix-and-re-drop**: when a job fails due to bad JSON or missing fields, the request file stays in `pending/` and the response file stays in `responses/`. Edit the response file, save, and the worker will pick it up within 2s. No API restart needed.
- **`extract_cast_char_limit`** (default 300 000) caps the book text substituted into `{BOOK_TEXT}`. On truncation the extract-cast API response + UI modal surface the spec-mandated warning telling the operator to use a single-book EPUB.
- **Narrative style** for auto-cast is currently hardcoded to `third-person limited with POV shifts` (TODO for per-project override in Phase 7).
