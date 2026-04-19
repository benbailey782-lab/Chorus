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
- Phase 4 (Per-Chapter Attribution) — **shipped**. Backend: schema v5 (adds `segments.text_modified`), `attribute_chapter` handler, `POST /api/chapters/{id}/attribute`, `POST /api/projects/{id}/attribute-all`, `GET /api/chapters/{id}/segments`, `PATCH /api/segments/{id}` (flips `text_modified=1` on text edits), `POST /api/segments/bulk-reassign`, `GET /api/segments/{id}/preview` → 501 until Voicebox. Full review UI at `/project/:idOrSlug/chapters/:chapterId`: prose view + table view, filter drawer (speaker, confidence range, render mode, emotion/notes toggles, persisted per-chapter), detail panel with inline editing + Cmd/Ctrl+Enter save, bulk operations (reassign speaker, set render mode, add/remove emotion tags, select-all), keyboard nav (j/k, Enter, Esc, ?). Casting page gains a Chapters section with progress bar, per-chapter status chips, inline Attribute/Review/Retry, and an "Attribute all" project-level action. Round-trip validated against AGoT BRAN via file-drop: 217 segments, mean confidence 96.9, project → `attributed`.
- Phase 5 (TTS Generation + Pronunciation Overrides) — **shipped backend + UI; live validation pending Mac + Voicebox**. Backend: schema v6 (adds `segments.approved_at`, `segments.status CHECK`, `pronunciations_global`, `projects.generation_config_json`); typed Voicebox httpx client with `synthesize()` thin wrapper; `GET /api/voicebox/status` canonical (old path 308 redirect); pronunciation system (global + project-scoped tables, Pass 3 file-drop handler, 11 REST endpoints, project-overrides-global merge); generation pipeline (`backend/audio/generation.py`, direct-mode job handler, 9 REST endpoints, path layout `data/projects/<id>/audio/{raw,approved}/<chapter_id>/segment_<id>.<ext>` with Content-Type sniffing). Frontend: Pronunciations pages (project + global), Chapter Review Generate button + estimate modal + progress bar + per-segment audio icons + DetailPanel Audio section (Play/Regenerate/Approve/Reject), bulk audio actions. All TTS call paths gracefully degrade when `VOICEBOX_ENABLED=false`: jobs fail with clear errors, UI surfaces disabled state + "Voicebox disabled" chip. Flipping the flag on a Mac with live Voicebox enables generation without code changes.
- Phase 6 (Player + Playback UI) — **shipped backend + UI; validated end-to-end on Windows with silent placeholder audio**. Backend: schema v7 (rebuilt `playback_state` with `chapter_id`/`current_segment_id`/`speed`; new `chapter_assemblies` cache table); `backend/audio/assembly.py` orchestration (ffmpeg concat + transcode to canonical pcm_s16le/44.1kHz/mono; SHA-256 `segment_hash` cache key; `asyncio.Semaphore(1)` serialization); 4 assembly endpoints (`POST /assemble`, `GET /audio` strict-404, `GET /assembly-status`, `GET /segment-timings`); 2 playback-state endpoints; direct-mode `assemble_chapter` handler; invalidation hooks in Phase 5 generate/regenerate/approve/reject paths. Frontend: `<Layout>` wrapper with persistent `<MiniPlayer>`; full player at `/play/:idOrSlug` (desktop 3-column; mobile single-column with bottom-sheet synced text); 8 player components (TransportControls, Scrubber, SpeedControl, ChapterList, SyncedTextView, IncompleteChapterDialog, CoverArt, MiniPlayer); pitch-preserving speed control via native `HTMLMediaElement.preservesPitch` (no library); Zustand `playerStore` (first cross-route store in Chorus); PlayerController singleton; auto-advance on chapter end (window CustomEvent); keyboard shortcuts. `/player` now serves Continue Listening + All Projects. Dev tool: `scripts/generate_placeholder_audio.py` writes silent WAVs matching each segment's estimated duration (word_count / wps_factor clamped 1–30s) so the full player can be tested without Voicebox. Live Voicebox + Mac validation pending.
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
- **`text_modified` column** on segments. Flipped to `1` by `PATCH /api/segments/{id}` when the request body contains `text` and the new value differs from the stored value. Re-attribution of a chapter currently wipes all segments including user edits — smarter merge deferred to Phase 7.

### Phase-5 backend conventions

- **`jobs.kind = "generate_segment"`** — direct handler (not file-drop). Registered via `@register_handler("generate_segment", mode="direct")`. Payload: `{segment_id, force?}`. Worker dispatches queued direct jobs via a parallel loop (see `backend/jobs/worker.py`).
- **`jobs.kind = "pronounce_unusual"`** — file-drop handler. Payload: `{project_id}`. Response maps `word`→`term` and `respelling`→`phonetic` when inserting.
- **Voicebox integration**: all calls go through `backend/voices/voicebox_client.py`. `VoiceboxNotEnabled` when flag off; `VoiceboxUnreachableError` on network failure; generic `VoiceboxError` superclass. Endpoint assumptions are spec-derived — see `docs/VOICEBOX-WIRING.md` for the verification punchlist.
- **Audio layout**: `data/projects/<project_id>/audio/raw/<chapter_id>/segment_<segment_id>.<ext>` and `/approved/` equivalent. Approve copies raw→approved (preserves source); Reject clears `approved_at` only (file stays). Regenerate wipes raw + approved files for that segment before re-generating.
- **Pronunciation merge**: `backend/nlp/merge_pronunciations.py` → project entries override global by lowercase term. Longest-term-first regex substitution (`Lord Varys` wins over `Varys`). Pure lowercase swap (phonetic is canonical).
- **Generation concurrency**: `asyncio.Semaphore(settings.voicebox_max_concurrent_generations)` (default 1 — serial). Forward-compat; bump when Voicebox proves stable on Mac.
- **Voicebox port**: default `8090` (avoids Vite 5173 + Chorus backend 8765 collisions). Override via `VOICEBOX_BASE_URL`.

### Phase-6 backend conventions

- **`jobs.kind = "assemble_chapter"`** — direct-mode handler. Payload: `{chapter_id, force}`. Progress updates at 20/60/90/100 (concat-list written / ffmpeg done / ffprobe done / row upserted).
- **Audio layout (extended from Phase 5)**: `raw/` + `approved/` + `assembled/<chapter_id>.wav`. Assembled files are a pure disk+DB cache; never committed to git (gitignored via the `data/` rule).
- **Cache invalidation is forward-looking**: any state change that *will* affect a chapter's audio state (generate, regenerate, approve, reject) invalidates the cached assembly immediately — even before the new audio lands. Next play re-assembles. Helper is best-effort and never raises.
- **ffmpeg is a required runtime dep** on any machine that plays audio. Fail loudly if missing via `FfmpegMissingError`. Install: `choco install ffmpeg` / `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (Mac).
- **Windows asyncio**: `backend/main.py` sets `WindowsProactorEventLoopPolicy` because the default `SelectorEventLoop` doesn't support `asyncio.create_subprocess_exec`. Required for ffmpeg-based assembly.

### Phase-6 frontend conventions

- **State tiering** (project-wide rule, codified in Phase 6): **TanStack Query for server state, Zustand for cross-route client state, `useState` for component-local state.** `playerStore` is the first Zustand store — add future cross-route stores under `frontend/src/stores/` following the same pattern.
- **Audio ownership**: the `playerController` singleton owns the single `HTMLAudioElement` instance. UI components **never** create their own audio elements.
- **Player route vs player tab**: `/play/:idOrSlug` is the full player (single project). `/player` is the Continue Listening / All Projects tab.
- **Layout wrapper**: all routes nest under `<Layout />` which mounts BottomNav + MiniPlayer + ToastContainer. Add to this wrapper for future always-on UI (e.g., a global command palette).
- **Pitch preservation**: use native `HTMLMediaElement.preservesPitch` (set all three vendor prefixes). Do **NOT** add `soundtouch-js` or `rubberband-web` unless the user reports quality issues at extreme speeds.
- **Auto-advance preference**: `player:auto-advance` in `localStorage`, default `true`. Not a DB column — it's a client preference.

### Phase-5 frontend conventions

- **Pronunciation manager** is a single shared component (`frontend/src/components/pronunciations/PronunciationManager.tsx`) parameterized by `scope: "global"|"project"`. Mounted by both `/settings/pronunciations` and `/project/:idOrSlug/pronunciations`.
- **Audio state** helper at `frontend/src/components/review/segment-audio.tsx` is the single source of truth: `getSegmentAudioState(seg)` returns `"none"|"generating"|"generated"|"approved"|"error"`. Never hardcode state logic elsewhere.
- **Voicebox health** is queried via `useQuery(["voicebox-health"], api.voiceboxHealth, { staleTime: 30_000 })` — reused across Chapter Review + Voice Library + any future TTS surface. Don't duplicate the query.
- **Generate button UX**: disabled when estimate says 0 ungenerated segments; `btn-surface` style when Voicebox not reachable (still clickable to open the modal and explain why); `btn-primary` only when Voicebox is fully ready.

### Phase-4 frontend conventions

- **Review UI route**: `/project/:idOrSlug/chapters/:chapterId` → `ChapterReview.tsx`. Two-pane desktop (prose/table left, detail panel right); bottom-sheet detail on mobile.
- **Confidence thresholds** are single-sourced from `frontend/src/lib/constants.ts::CONFIDENCE`. Green ≥85, yellow 70–84, red <70, neutral for null. Any time you add a color-coded surface for confidence, import from there — do not hardcode thresholds.
- **Filter persistence**: per-chapter in localStorage, key `review:filters:{chapterId}`. View mode preference under `review:view-mode`. Helpers in `frontend/src/lib/review-filters.ts`.
- **Toast system**: minimal custom toast in `frontend/src/lib/toast.ts` + `frontend/src/components/Toast.tsx`. Wrapped at app root. Import `useToast()` to emit. Do not add a third-party toast lib.
- **Bulk operations** that can be expressed as a single `changes` payload (speaker, render_mode) use `POST /api/segments/bulk-reassign`. Add/remove emotion tags require per-segment PATCHes because the bulk endpoint applies the same `changes` to every selected segment (would overwrite per-segment tag lists).

### Phase-3 conventions

- **Job `kind` vs spec's `type`**: the v1 DB schema used `kind`. We keep it for compatibility and map in-code vocabulary: `extract_characters`, `auto_cast`, `attribute_chapter` (Phase 4), etc. Spec §9.8 calls the column `type` — treat the two names as synonymous.
- **Handlers bind at import**: `backend/main.py` imports `extract_characters` and `auto_cast` so their `@register_handler` decorators fire before the worker starts. Any new handler added in a later phase must be imported in `main.py` too, or the worker will fail its job with "no handler registered".
- **Response retries are fix-and-re-drop**: when a job fails due to bad JSON or missing fields, the request file stays in `pending/` and the response file stays in `responses/`. Edit the response file, save, and the worker will pick it up within 2s. No API restart needed.
- **`extract_cast_char_limit`** (default 300 000) caps the book text substituted into `{BOOK_TEXT}`. On truncation the extract-cast API response + UI modal surface the spec-mandated warning telling the operator to use a single-book EPUB.
- **Narrative style** for auto-cast is currently hardcoded to `third-person limited with POV shifts` (TODO for per-project override in Phase 7).
