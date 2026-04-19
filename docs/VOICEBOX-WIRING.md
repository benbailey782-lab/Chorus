# Voicebox Wiring Punchlist

Chorus is developed on Windows, where Voicebox isn't installed. Every TTS call
goes through `backend/voices/voicebox_client.py`, which short-circuits with
`VoiceboxNotEnabled` whenever `VOICEBOX_ENABLED=false` (the default). The
production target is a Mac running Voicebox alongside Chorus. This doc is the
checklist of verification work the first time real Voicebox is online.

## Status as of Phase 5

- Schema (v6): `segments.status` CHECK constraint covers
  `pending|generating|generated|approved|error`; `segments.approved_at`
  populated on approve; `projects.generation_config_json` carries per-project
  overrides (reserved; not yet authored by the UI).
- Typed HTTP client (`backend/voices/voicebox_client.py`) with async `httpx`
  session, typed dataclasses, structured exceptions, retry-on-transient policy.
- Thin-wrapper `synthesize()` — the canonical "give me audio for this text"
  entrypoint. Internally: `generate()` → poll `get_generation()` until
  `status in {"done","error"}` → `download_generation_audio()` → return
  `(bytes, content_type)`.
- Canonical health endpoint: `GET /api/voicebox/status`. Legacy path
  `GET /api/voices/voicebox/status` returns HTTP 308 Permanent Redirect to the
  canonical path and is kept only so old clients don't 404 during rollout.

## Config surface

Defaults live in `backend/config.py` (`Settings` via pydantic-settings):

| Setting                              | Default                    | Env var                                 |
|---|---|---|
| `voicebox_enabled`                   | `False`                    | `VOICEBOX_ENABLED`                      |
| `voicebox_base_url`                  | `http://localhost:8090`    | `VOICEBOX_BASE_URL`                     |
| `voicebox_timeout_seconds`           | `120`                      | `VOICEBOX_TIMEOUT_SECONDS`              |
| `voicebox_default_wps`               | `2.5`                      | `VOICEBOX_DEFAULT_WPS`                  |
| `voicebox_output_sample_rate`        | `44100`                    | `VOICEBOX_OUTPUT_SAMPLE_RATE`           |
| `voicebox_max_concurrent_generations`| `1`                        | `VOICEBOX_MAX_CONCURRENT_GENERATIONS`   |

**Port note.** Default port moved from `5173` (Voicebox upstream default) to
`8090` to avoid collision with Vite (`5173`) and the Chorus backend (`8765`)
when all three run on the same Mac. If you run Voicebox on its upstream default,
set `VOICEBOX_BASE_URL=http://localhost:5173`.

**Concurrency note.** `max_concurrent_generations` defaults to `1` (serial).
Generation is gated by `asyncio.Semaphore(N)` in
`backend/audio/generation.py`. Forward-compatible; bump after Mac/Voicebox soak.

## Flipping the flag

```bash
# .env in the repo root (not committed)
VOICEBOX_ENABLED=true
VOICEBOX_BASE_URL=http://localhost:8090
```

Restart the backend. Verify:

```bash
curl http://localhost:8765/api/voicebox/status
# → {"enabled": true, "reachable": true, "base_url": "http://localhost:8090", ...}
```

When `enabled: true` but `reachable: false`, startup still succeeds. The UI
surfaces the state via the `voicebox-health` query used by Chapter Review, the
Voice Library, and any future TTS surface.

## Exception hierarchy

All defined in `backend/voices/voicebox_client.py`:

- `VoiceboxError(RuntimeError)` — base class; catch this to handle any
  Voicebox-originated failure.
  - `VoiceboxNotEnabled` — `settings.voicebox_enabled is False`. Caller should
    degrade gracefully (skip, show disabled state, etc.).
  - `VoiceboxUnreachableError` — **canonical** network / HTTP error (connection
    refused, non-2xx after retries, DNS failure). All new code should catch
    this.
  - `VoiceboxUnreachable` — legacy alias; kept as a subclass of
    `VoiceboxError` for import compatibility. Delete when no old call sites
    remain.
  - `VoiceboxTimeoutError` — `synthesize()` exceeded
    `voicebox_timeout_seconds` while polling.
  - `VoiceboxGenerationFailed` — Voicebox returned `status == "error"` in the
    generation body (distinct from transport failures).

## Endpoint assumption punchlist — `TODO(voicebox-verify)`

Every row below is a **design-time assumption** derived from §12.2 of
`CHORUS-SPEC.md`. Before running live, open Voicebox's `/docs` (FastAPI /
OpenAPI UI at `{base_url}/docs`) and walk the list. Update the real shape in
this doc first, then in the client.

### 1. Health probe `GET /` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | Reachability check; never raises. Returns `VoiceboxStatus`. |
| Assumed request | No body. Any 2xx counts as reachable. |
| Assumed response | Anything. We only read status code + optional `version` JSON field. |
| Verify | `curl {base_url}/` — confirm it 200s. If Voicebox only exposes `/api/health`, swap the probe path. |

### 2. `GET /api/profiles` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | List all Voicebox profiles. Not yet wired into Chorus flows — exists for a future "reconcile" admin view. |
| Assumed request | No body. |
| Assumed response | JSON array: `[{id, display_name, engine, created_at, sample_url}]`. |
| Verify | Hit `/docs`, compare against the "List Profiles" schema. Field names most likely to drift: `display_name` (could be `name`), `sample_url` (could be `preview_url`). |

### 3. `POST /api/profiles` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | Clone a voice from reference audio. Called when a Chorus voice with a reference audio file is created or has its audio replaced. |
| Assumed request | `multipart/form-data` with `audio` (WAV/MP3/FLAC/M4A/OGG, ≤25 MB), `display_name` (string), `metadata` (JSON string). |
| Assumed response | `{id, display_name, engine, sample_url, created_at}`. Chorus persists `id` onto `voices.voicebox_profile_id`. |
| Verify | `/docs` — confirm multipart fields names, max size, response `id` key. |

### 4. `POST /api/generate` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | Kick off a generation. Called by `synthesize()` before polling. |
| Assumed request (JSON) | `{text, profile_id, engine?, effects?}` where `effects` is `{reverb, pre_silence_ms, post_silence_ms, paper_filter}`. |
| Assumed response | `{generation_id, status, progress, audio_url?}` — `status ∈ {"queued","running","done","error"}`. |
| Verify | `/docs`. Effect key names likely to drift (Voicebox may call it `fx` or flatten into top-level fields). |

### 5. `GET /api/generations/{id}` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | Poll an in-flight generation. `synthesize()` loops on this until `status` is terminal. |
| Assumed request | No body. |
| Assumed response | Same shape as `/api/generate` response plus `error?` on failure. |
| Verify | `/docs`. Also confirm the poll cadence Voicebox is happy with (we use 1s with jitter). |

### 6. `GET /api/generations/{id}/audio` — `TODO(voicebox-verify)`

| | |
|---|---|
| Purpose | Fetch the rendered audio binary. Called once `status == "done"`. |
| Assumed request | No body. |
| Assumed response | Binary; `Content-Type: audio/wav`, `audio/mpeg`, `audio/flac`, or `audio/ogg`. Chorus sniffs the header and picks the extension. Unknown → `.wav` with warning log. |
| Verify | `/docs` + a real fetch with `curl -v` to see the exact `Content-Type` header. |

## `synthesize()` — the thin wrapper

Signature (see `backend/voices/voicebox_client.py`):

```python
async def synthesize(req: VoiceboxSynthesisRequest) -> tuple[bytes, str]:
    ...
```

Behavior:

1. Raises `VoiceboxNotEnabled` if flag off.
2. Calls `generate()` to get a `generation_id`.
3. Polls `get_generation()` with bounded backoff until `status` is terminal or
   `voicebox_timeout_seconds` elapses.
4. On `status == "error"`, raises `VoiceboxGenerationFailed` with the
   server-supplied `error` field.
5. On `status == "done"`, calls `download_generation_audio()` and returns
   `(bytes, content_type)`.

All transport errors bubble up as `VoiceboxUnreachableError`.

## Verification checklist on first Mac + Voicebox run

1. Start Voicebox on the Mac. Confirm `{base_url}/docs` renders.
2. Set `VOICEBOX_ENABLED=true`, restart Chorus backend.
3. `curl http://localhost:8765/api/voicebox/status` → expect `reachable: true`.
4. Walk the punchlist above. For each mismatch: update this doc first, then
   update the typed client, then drop the `TODO(voicebox-verify)` marker.
5. Create a voice with reference audio via the UI → confirm
   `voices.voicebox_profile_id` is populated in SQLite.
6. Generate a single segment via Chapter Review → confirm `data/projects/<id>/audio/raw/<chapter_id>/segment_<segment_id>.<ext>` appears on disk with a sensible extension.
7. Approve the segment → confirm the file is copied under `audio/approved/`.

Only after every `TODO(voicebox-verify)` has been resolved should §12.2 of
`CHORUS-SPEC.md` be marked verified.
