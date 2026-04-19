# Voicebox Wiring Reference

**Verified against Voicebox v0.4.0** — the live API has been walked end-to-end
against `backend/voices/voicebox_client.py`. As of 2026-04-18 every Chorus
call site routes through a typed wrapper around a real endpoint. Treat this
file as the authoritative integration reference; `CHORUS-SPEC.md` §12 points
here for any concrete API question.

> Historical context: Phase 5 originally shipped against a stubbed
> `TODO(voicebox-verify)` punchlist. That punchlist was retired in the Phase 5
> Remediation pass (commits `6aa646d` … `91a32da`). See
> `docs/PHASE-5-REMEDIATION.md` for the decision log.

---

## Config

Voicebox runs at a runtime-assigned port and is **not** auto-discovered.
Operators paste the URL into Chorus once and Chorus persists it.

### Persistence layer

- **Per-install URL + enabled flag**: `data/voicebox_config.json`. Read on
  every request via `backend/voices/voicebox_config_store.get_effective()`.
  No backend restart needed when the value changes.
- **JSON shape**: `{"voicebox_base_url": "http://localhost:17493",
  "voicebox_enabled": true, "updated_at": "..."}`.
- **Settings UI path**: Settings → Voicebox section. Three controls: URL
  input, "Test connection" button (calls `POST /api/voicebox/test-connection`
  without persisting), and an Enable toggle. "Save" writes the JSON file.

### Fallback order

1. `data/voicebox_config.json` if present and parseable.
2. Environment variables (`VOICEBOX_BASE_URL`, `VOICEBOX_ENABLED`).
3. `VoiceboxSettings` defaults (URL `""` — empty/unconfigured —, enabled
   `False`).

### `VoiceboxSettings` defaults

| Setting                              | Default | Env var                                 |
|---|---|---|
| `voicebox_enabled`                   | `False` | `VOICEBOX_ENABLED`                      |
| `voicebox_base_url`                  | `""`    | `VOICEBOX_BASE_URL`                     |
| `voicebox_timeout_seconds`           | `120`   | `VOICEBOX_TIMEOUT_SECONDS`              |
| `voicebox_generation_timeout_seconds`| `600`   | `VOICEBOX_GENERATION_TIMEOUT_SECONDS`   |
| `voicebox_default_wps`               | `2.5`   | `VOICEBOX_DEFAULT_WPS`                  |
| `voicebox_max_concurrent_generations`| `1`     | `VOICEBOX_MAX_CONCURRENT_GENERATIONS`   |

The empty-string URL default is intentional: Chorus runs in fully-disabled
mode out of the box and only activates Voicebox after the operator has
explicitly configured a URL.

---

## Exception hierarchy

All defined in `backend/voices/voicebox_client.py`:

- `VoiceboxError(RuntimeError)` — base; catch this to handle any
  Voicebox-originated failure.
  - `VoiceboxNotConfigured` — no URL set in config or env.
  - `VoiceboxDisabled` — `voicebox_enabled is False`.
    - `VoiceboxNotEnabled` — legacy alias retained for Phase 5 import sites.
  - `VoiceboxUnreachable` — canonical network/transport failure.
    - `VoiceboxUnreachableError` — legacy alias retained for Phase 5 import sites.
  - `VoiceboxAPIError` — non-2xx response with parseable error body.
  - `VoiceboxGenerationError` — Voicebox returned `status=="error"` on a
    generation.
    - `VoiceboxGenerationFailed` — legacy alias.
  - `VoiceboxTimeoutError` — polling exceeded
    `voicebox_generation_timeout_seconds`.
  - `VoiceboxModelNotLoaded` — generation attempted without the engine's
    model in memory; raised by the lazy loader before falling through to
    Voicebox.

Legacy aliases are kept so Phase 5 call sites that catch
`VoiceboxUnreachableError` / `VoiceboxNotEnabled` / `VoiceboxGenerationFailed`
continue to work without touching their imports.

---

## Endpoints wired

One row per `voicebox_client.py` function. Chorus call site → real Voicebox
v0.4.0 endpoint → notes.

| Chorus client function          | Voicebox endpoint                      | Notes                                                                 |
|---|---|---|
| `health_check()`                | `GET /health`                          | Returns `VoiceboxHealth`. Never raises; reachability bool surfaced.  |
| `list_models()`                 | `GET /models/status`                   | Returns `[ModelStatus]` with downloaded + loaded flags.              |
| `get_model_status(name)`        | `GET /models/status` (filtered)        | Convenience wrapper around `list_models()`.                          |
| `load_model(name)`              | `POST /models/load` `{model_name}`     | Async on Voicebox side; poll `get_model_progress`.                   |
| `unload_model(name)`            | `POST /models/{name}/unload`           | Frees VRAM/RAM.                                                      |
| `download_model(name)`          | `POST /models/download` `{model_name}` | Triggers download; poll progress.                                    |
| `get_model_progress(name)`      | `GET /models/progress/{name}`          | `{progress: 0..1, status, message}`. Used by lazy loader.            |
| `list_profiles()`               | `GET /profiles`                        | Returns all Voicebox profiles.                                       |
| `get_profile(id)`               | `GET /profiles/{id}`                   | Returns a single profile.                                            |
| `create_profile(...)`           | `POST /profiles` (JSON body)           | JSON body — does NOT include sample audio. Sample uploaded separately. |
| `update_profile(id, ...)`       | `PUT /profiles/{id}`                   | Patch metadata in place.                                             |
| `delete_profile(id)`            | `DELETE /profiles/{id}`                | Cascades inside Voicebox.                                            |
| `add_sample_to_profile(...)`    | `POST /profiles/{id}/samples`          | **multipart/form-data; reference_text REQUIRED**. Voicebox transcribes against it. |
| `list_preset_voices(engine)`    | `GET /profiles/presets/{engine}`       | Pre-built voice library per engine. Tier C source.                   |
| `generate(...)`                 | `POST /generate`                       | Body: `{text, profile_id, model_name, options?}`.                    |
| `get_generation_status(id)`     | `GET /generate/{id}/status`            | `status ∈ {queued, running, complete, error, cancelled}`.            |
| `cancel_generation(id)`         | `POST /generate/{id}/cancel`           | Idempotent.                                                          |
| `regenerate(id)`                | `POST /generate/{id}/regenerate`       | Reuses original profile + parameters; returns a new generation_id.   |
| `retry_generation(id)`          | `POST /generate/{id}/retry`            | Like regenerate but for failed generations specifically.             |
| `get_generation_audio(id)`      | `GET /audio/{id}`                      | Returns `(bytes, content_type)`. Sniffed for extension.              |

---

## High-level wrappers

These are the entry points the rest of Chorus actually calls. All three
follow the same polling + download pattern and respect
`settings.voicebox_generation_timeout_seconds` (default 600s).

### `generate_and_wait(profile_id, text, model_name, options) -> SynthesisResult`

1. `POST /generate` to kick off; capture `generation_id`.
2. Poll `GET /generate/{id}/status` with bounded backoff (1 s base, jittered).
3. On terminal `complete`: `GET /audio/{id}` → returns bytes + content_type.
4. On terminal `error`: raise `VoiceboxGenerationError`.
5. On polling timeout: raise `VoiceboxTimeoutError` (but the in-flight
   generation is NOT cancelled server-side — the caller can recover the
   generation_id from the exception if needed).

Returns a `SynthesisResult` with `audio_bytes`, `content_type`,
`duration_ms`, and `generation_id` (the latter persisted onto
`segments.voicebox_generation_id`).

### `regenerate_and_wait(generation_id) -> SynthesisResult`

Same shape. Uses `POST /generate/{id}/regenerate` for the kickoff so the
profile + parameters are reused server-side. The "Regenerate" button in
DetailPanel routes through this when `segments.voicebox_generation_id` is
non-null; otherwise it falls back to a fresh `generate_and_wait`.

### `retry_and_wait(generation_id) -> SynthesisResult`

Same shape. Uses `POST /generate/{id}/retry`. Wired to the per-segment
**Retry** button (Phase 5R) for segments whose previous generation ended in
`error`.

---

## Lazy model loading

`backend/audio/model_loader.py::ensure_model_loaded(engine)` is idempotent
and safe to call before every generation:

- **In-process cache** of `{engine: True}` for the lifetime of the backend
  process. First call per engine triggers a `POST /models/load` and polls
  `GET /models/progress/{name}` until `progress >= 1.0`.
- **Per-model `asyncio.Lock`** so concurrent generations of the same engine
  collapse onto a single load.
- **Surfaces progress** to the frontend via the `modelLoadingStore` Zustand
  store; the global `ModelLoadingBanner` reflects status messages and
  percent.
- **Skips work** when `GET /models/status` already shows the engine loaded.

Restarting the backend wipes the cache; the model itself stays loaded inside
Voicebox, so the second backend session sees it as already loaded and
returns immediately.

---

## Engine → model mapping

| Chorus engine value      | Voicebox model name        | Notes                                                                  |
|---|---|---|
| `qwen3-tts`              | `qwen-tts-1.7B`            | Verified loaded on Ben's install; default engine for new voices.       |
| `chatterbox-turbo`       | `chatterbox-turbo`†        | Paralinguistic tags supported (see below).                             |
| `chatterbox-multilingual`| `chatterbox-multilingual`† | Multi-language.                                                        |
| `luxtts`                 | `luxtts`†                  | Premium quality (engine docs).                                         |
| `humeai-tada`            | `humeai-tada`†             | 23+ languages.                                                         |
| `kokoro-82m`             | `kokoro-82m`†              | Small model, fast.                                                     |
| `qwen-custom-voice`      | `qwen-custom-voice`†       | Voice-cloning specialist.                                              |

† **Model name unverified.** The Chorus engine string is the canonical
key; the Voicebox model name is the operator-facing identifier shown in
the Voicebox UI's Models tab. If the on-disk model name differs from the
default mapping, set the override via the engine's metadata once the model
is downloaded — confirm in the Voicebox UI before reporting a mismatch.

---

## Paralinguistic tag mapping

Only applied when the voice's `voicebox_engine == 'chatterbox-turbo'`. All
other engines pass text through unmodified. Source of truth:
`backend/audio/paralinguistic.py::TAG_MAP`.

| Chorus `emotion_tag` | Voicebox inline tag | Notes                                  |
|---|---|---|
| `whispered`          | `[whisper]`         | Prepended to text.                     |
| `shouted`            | `[shout]`           | Prepended.                             |
| `muttered`           | `[mutter]`          | Prepended.                             |
| `amused`             | `[laugh]`           | Prepended.                             |
| `laughed`            | `[laugh]`           | Prepended (same target as `amused`).   |
| `sad`                | `[sigh]`            | Prepended.                             |
| `sighed`             | `[sigh]`            | Prepended (same target as `sad`).      |
| `shocked`            | `[gasp]`            | Prepended.                             |
| `gasped`             | `[gasp]`            | Prepended (same target as `shocked`).  |

**No mapping** (silently passed through, rely on text + voice timbre):
`trembling`, `cold`, `stern`, `angry`, `gentle`, `warm`, `calm`, `hushed`,
`emphatic`, `urgent`. These are emotional shadings that Chatterbox Turbo
doesn't expose as discrete tags; if upstream Voicebox adds support for any
of them later, extend `TAG_MAP` and ship a docs update.

Duplicate tags (e.g. `["whispered","whispered"]`) are deduplicated
order-preserving. Tags collapse to a single space-separated prefix:
`"[whisper] [sigh] The deserter died bravely."`.

---

## First-time setup flow

1. **Install Voicebox** from <https://github.com/jamiepine/voicebox> and run
   it. Read the bound port from the Voicebox UI (e.g. `localhost:17493` —
   the port is runtime-assigned, not hardcoded).
2. **Configure Chorus.** Open Settings → Voicebox. Paste the URL, click
   **Test connection** (expect a green "Voicebox v0.4.0 reachable"
   message), tick **Enable**, click **Save**. No backend restart needed —
   the next request reads the new value.
3. **Add voices** in the Voice Library. Each voice picks an engine from the
   dropdown (default `qwen3-tts`). On save, the backend eagerly creates a
   Voicebox profile and uploads the reference audio sample. Voices that
   fail to sync show a "Needs sync" badge — click it to retry.
4. **Trigger generation** from Chapter Review. The first generation per
   engine per backend process triggers `ensure_model_loaded`; the global
   banner shows `Loading qwen-tts-1.7B… 47%` with live progress.
5. **Subsequent generations are fast.** The model stays cached inside
   Voicebox (and Chorus's in-process flag), so subsequent generations skip
   the load step entirely.

---

## Troubleshooting

**"Model not loaded"** — Check the global ModelLoadingBanner. If stuck,
verify in the Voicebox UI's Models tab that the model is downloaded;
trigger a manual download there if not. Restart the Chorus backend to
clear the in-process cache and force a re-check.

**"Profile sync failed" / "Needs sync" badge on a voice** — The Voicebox
URL was likely wrong or unreachable when the voice was saved. Click the
sync button on the voice card; backend re-runs `create_profile` +
`add_sample_to_profile`. If it still fails, check the backend logs for the
underlying `VoiceboxAPIError` body.

**"Generation failed" on a single segment** — Open the Detail Panel for the
underlying `VoiceboxGenerationError` message. Most often: bad
profile_id (voice's `voicebox_profile_id` references a deleted Voicebox
profile — re-sync the voice), or unsupported text characters for the
engine. Retry button on the segment routes through `/retry`.

**"Voicebox unreachable"** — Settings → Voicebox → Test connection. If the
test fails: confirm Voicebox is actually running, confirm the URL matches
the port shown in Voicebox's UI, confirm no firewall blocking localhost.
The empty-URL default is treated as "not configured" rather than
"unreachable" — the banner copy differs.
