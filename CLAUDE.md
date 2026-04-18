# Chorus — Multi-Voice Theatrical Audiobook Generator

## Project at a glance

- **Spec:** `CHORUS-SPEC.md` — authoritative. Update this file when scope shifts.
- **Backend:** Python 3.11+, FastAPI, SQLite (`backend/`).
- **Frontend:** React 18 + Vite + TypeScript + Tailwind + Zustand + TanStack Query (`frontend/`).
- **LLM:** Anthropic SDK. Opus 4.7 for cast extraction + low-confidence attribution. Sonnet 4.6 for bulk per-chapter work.
- **TTS:** Voicebox REST API (expected at `VOICEBOX_BASE_URL`, default `http://localhost:5173` on Mac).
- **Deploy model:** Mac runs backend; phone connects via `http://chorus.local:8080` as a PWA.

## Current status

- Phase 0 (Foundation) — scaffolded.
- Phase 1 (Ingestion + Library) — TXT + EPUB ingestion, naive chapter detection, Library + Project views. Claude chapter-detection fallback not yet wired.
- Phase 2 (Voice Library) — **done in Voicebox-stub mode** (dev is on Windows, no Voicebox installed). Full CRUD + metadata + optional reference-audio upload + mobile-first dark UI at §15.8 tokens. Voicebox wiring punch-list: `docs/VOICEBOX-WIRING.md`.
- Later phases per spec §17.

## Conventions

- NLP prompts live in `backend/nlp/prompts/*.md` — edit those files, do not inline prompts in Python.
- SQLite schema in `backend/db.py` (single canonical `SCHEMA_SQL`). When you change the schema, bump `SCHEMA_VERSION` and add a migration in `_run_migrations` rather than mutating `SCHEMA_SQL` in place. Destructive migrations must abort with `MigrationAborted` if the affected table has rows.
- FastAPI binds `0.0.0.0:8080` so the phone can reach it on LAN.
- Vite dev server binds `0.0.0.0:5173` and proxies `/api` → backend `:8080`.
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
uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
(cd frontend && npm install && npm run dev -- --host 0.0.0.0)
```

Health check: `curl http://localhost:8080/api/health`.
From phone on same WiFi: `http://chorus.local:8080/api/health` (mDNS advertised).

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
