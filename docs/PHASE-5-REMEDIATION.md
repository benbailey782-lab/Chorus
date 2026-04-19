# Phase 5 Remediation — Voicebox Integration Update

> Planning document for a focused Phase 5-remediation session after Phase 6 ships.
> Triggered by the discovery that Voicebox has dramatically more capabilities than originally specced, AND runs on Windows (no Mac requirement for production).

---

## Context

Phase 5 was built with stubbed `TODO(voicebox-verify)` comments throughout `backend/voices/voicebox_client.py` because the Voicebox API couldn't be verified without the service running.

On 2026-04-19, Ben discovered:
1. Voicebox has full Windows support (pre-built installer available at github.com/jamiepine/voicebox)
2. Voicebox v0.4.0 has 7 TTS engines (was assumed to be single-engine)
3. Voicebox has a full effects pipeline, multi-sample profile support, generation versioning, and a timeline editor
4. Voicebox runs at runtime-discovered port (localhost:17493 in Ben's install — not hardcoded 8090)

This remediation updates Chorus to match reality and unlock the new capabilities.

---

## Voicebox API inventory (verified against v0.4.0 `/docs`)

### Core endpoints Chorus uses today (names need updating)

| Chorus assumption | Real Voicebox API | Change needed |
|---|---|---|
| `POST /api/synthesize` | `POST /generate` | Endpoint rename |
| `GET /api/health` | `GET /health` | Path prefix removal |
| `GET /api/profiles` | `GET /profiles` | Path prefix removal |
| `POST /api/profiles` | `POST /profiles` | Path prefix removal |
| `DELETE /api/profiles/{id}` | `DELETE /profiles/{id}` | Path prefix removal |

### Endpoints Chorus doesn't use but should

| Endpoint | Purpose | Chorus use case |
|---|---|---|
| `POST /models/load` | Load a TTS model into memory | Call on startup or first generation |
| `POST /models/download` | Download a model | First-time setup wizard |
| `GET /models/status` | Which models are downloaded/loaded | Show in UI |
| `GET /generate/{id}/status` | Async generation status | Polling pattern (replaces sync synthesize) |
| `GET /audio/{generation_id}` | Download generated audio | After status=complete |
| `POST /generate/{id}/cancel` | Cancel in-progress generation | User-facing cancel button |
| `GET /profiles/presets/{engine}` | Pre-built voice library per engine | Free Tier C background voices |

### Endpoints Chorus should adopt in Phase 7+

| Endpoint | Purpose | Chorus use case |
|---|---|---|
| `POST /profiles/{id}/samples` | Add sample to existing profile | Multi-sample voices (better clone quality) |
| `PUT /profiles/{id}/effects` | Assign effect preset to voice | Per-character audio treatment |
| `GET /effects/available` | List effect types | UI for effect preset builder |
| `GET /effects/presets` | Saved effect presets | Character sonic identity library |
| `POST /generations/{id}/versions/apply-effects` | Create variant of existing generation | A/B compare different treatments |
| `GET /generations/{id}/versions` | Multiple versions per segment | Replace "regenerate overwrites" with version history |
| `GET /profiles/{id}/channels` / `POST /channels` | Audio channel routing | TBD — needs deeper investigation |

### Capabilities flagged but not integrating

| Endpoint group | Reason to skip (for now) |
|---|---|
| `/stories/*` | Voicebox has its own multi-voice timeline editor. Chorus does chapter-level assembly via ffmpeg and should continue to (preserves per-segment review). Could integrate later as an alternative assembly path. |
| `/transcribe` | Whisper built-in. Not in Chorus's current needs. Could use for QA (verify generated text matches intended) in future. |
| `POST /generate/stream` | Streaming generation. Could enable "play as you generate" but our review-then-approve workflow doesn't need it. |

---

## TTS engines available in Voicebox v0.4.0

| Engine | Strengths | Paralinguistic tags | Recommended Chorus use |
|---|---|---|---|
| Qwen3-TTS | General-purpose cloning, proven quality | No | Default engine for all voices |
| LuxTTS | Specialization TBD (need to read engine docs) | TBD | TBD |
| Chatterbox Multilingual | Multi-language support | No | International character voices |
| **Chatterbox Turbo** | Expressive speech with emotion tags like [laugh], [sigh], [gasp] | **Yes** | Dialogue-heavy voices, emotionally expressive characters |
| HumeAI TADA | Broadest language coverage (23+ languages including Arabic, Hindi, Japanese, Swahili) | No | Non-English books, foreign character voices |
| Kokoro 82M | Small model, likely faster, quality TBD | TBD | Bulk Tier C background voices |
| Qwen CustomVoice | Likely the voice cloning specialist | TBD | TBD |

**Recommended engine strategy:**
- Tier A hero voices: Chatterbox Turbo (paralinguistic tags mapped from emotion_tags)
- Tier B supporting voices: Qwen3-TTS (consistent default quality)
- Tier C background voices: Kokoro 82M (speed + bulk) OR preset voices from /profiles/presets/{engine}
- Foreign-language content: HumeAI TADA

---

## Paralinguistic tag mapping

Chorus has `emotion_tags` on each segment (from Phase 4 attribution prompt). When voice uses Chatterbox Turbo, map to paralinguistic tags:

| Chorus emotion_tag | Voicebox paralinguistic tag | Mapping strategy |
|---|---|---|
| whispered | [whisper] or similar | Prepend to segment text |
| shouted | [shout] | Prepend |
| muttered | [mutter] | Prepend |
| laughed / amused | [laugh] or [chuckle] | Prepend |
| sighed / sad | [sigh] | Prepend |
| gasped / shocked | [gasp] | Prepend |
| trembling | [tremble] (if supported) | Prepend |
| cold / stern / angry | No direct mapping — rely on text + voice | Passthrough |
| gentle / warm / calm | No direct mapping | Passthrough |

**Open question:** which exact tag names does Chatterbox Turbo recognize? README mentions `[laugh]`, `[chuckle]`, `[gasp]`, `[cough]`, `[sigh]`, `[groan]`, `[sniff]`, `[shush]`, `[clear throat]`. Need to verify full tag vocabulary via testing.

**Implementation location:** backend/audio/generation.py, in `prepare_text_for_tts(segment, voice)` — reads voice's engine + emotion tags, produces final text to send.

---

## Schema changes required

### Migration v7 → v8 (after Phase 6 ships)

**voices table additions:**
```sql
ALTER TABLE voices ADD COLUMN voicebox_engine TEXT DEFAULT 'qwen3-tts'
  CHECK (voicebox_engine IN ('qwen3-tts','luxtts','chatterbox-multilingual','chatterbox-turbo','humeai-tada','kokoro-82m','qwen-custom-voice'));
ALTER TABLE voices ADD COLUMN voicebox_effect_preset_id TEXT;  -- nullable; references voicebox-side preset
```

**voice_samples table (new):**
```sql
CREATE TABLE voice_samples (
  id TEXT PRIMARY KEY,
  voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
  sample_path TEXT NOT NULL,  -- local path in data/voice_library/samples/
  voicebox_sample_id TEXT,    -- nullable; set when synced with Voicebox profile
  label TEXT,                 -- e.g., "Beheading scene", "Civ VI narration"
  duration_ms INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Migration preserves existing voice.sample_path as the first entry in voice_samples.

---

## Client refactor scope

### backend/voices/voicebox_client.py changes

**Remove:**
- `/api/` prefix from all endpoint paths
- `synthesize()` method — replaced by `generate_and_wait()`

**Add:**
- `generate_and_wait(profile_id, text, engine, options) -> (audio_bytes, duration_ms)` — wraps POST /generate + poll /generate/{id}/status + download from /audio/{generation_id}
- `list_models() -> list[ModelStatus]`
- `load_model(model_name)` — ensures model is loaded before generation
- `ensure_model_for_engine(engine)` — loads the right model for a given engine
- `get_model_progress(model_name)` — download progress
- `download_model(model_name)` — triggers download
- `list_preset_voices(engine) -> list[PresetVoice]` — for Tier C bulk
- `add_sample_to_profile(profile_id, audio_bytes, label) -> SampleResponse`
- `list_samples(profile_id) -> list[SampleResponse]`
- `delete_sample(sample_id)`
- `get_effects_available() -> list[EffectConfig]`
- `list_effect_presets() -> list[EffectPreset]`
- `apply_effect_preset_to_profile(profile_id, preset_id)`

**Update:**
- `VoiceboxSettings.voicebox_base_url` default — `http://localhost:8090` was a guess. Real Voicebox binds to a runtime-assigned port (Ben's install used 17493). Detection strategy:
  - Try common ports (8090, 17493, 5173 — but 5173 collides with Vite) — no, runtime-assigned means we can't guess
  - **Better:** surface a "Voicebox URL" config field in Chorus settings, user pastes from Voicebox UI
  - **Even better:** query a well-known local config file if Voicebox writes one (investigate)

### backend/audio/generation.py changes

- Replace direct `voicebox.synthesize()` with `voicebox.generate_and_wait()`
- Add `prepare_text_for_tts(segment, voice)` for paralinguistic tag mapping
- Add `ensure_voice_ready(voice)` — checks Voicebox profile exists, syncs if needed, ensures model is loaded
- Update error handling: new failure modes (model not loaded, model downloading, generation cancelled)

### New backend/voices/models.py

- `ensure_default_model_loaded()` — called on startup if VOICEBOX_ENABLED
- UI endpoint `GET /api/voicebox/models/status` — surfaces model state to frontend

---

## UI additions (Phase 7 polish scope)

1. **Settings page addition:** Voicebox URL configuration (paste from Voicebox UI)
2. **First-time setup wizard:** detect Voicebox unreachable on config → prompt to configure URL → verify connection → pick default engine → trigger model download → wait for completion
3. **Voice edit UI:** engine dropdown + effect preset dropdown
4. **Multi-sample management:** add/remove/list samples per voice, with playback of each
5. **Generation status UI:** show "Loading model..." states cleanly; progress bar for downloads
6. **Model management panel** (Settings): list downloaded models, delete models to reclaim disk, download new models

---

## Performance considerations

Ben's Windows machine: CPU-only (no GPU detected at Voicebox install).

**Expected performance on CPU:**
- Qwen3-TTS: likely 5-20 seconds of wall-clock per 10 seconds of audio
- Chatterbox Turbo: similar or slightly slower
- Kokoro 82M: likely faster (smaller model)

**Implication for Chorus:**
- 217-segment chapter × avg 7s audio per segment × 10s CPU-time per generated second = ~4 hours wall-clock to generate BRAN
- Not acceptable for iteration

**Options:**
1. Generate on Mac (MLX = 4-5x faster per README)
2. Enable CUDA on Windows if Ben has/adds an NVIDIA GPU
3. Accept slow generation and run overnight
4. Use Kokoro 82M for speed, accepting quality tradeoff

**Recommendation:** Generate hero chapters on Mac, let Tier C bulk voices generate on Windows overnight.

---

## Prerequisites Ben needs to satisfy before Phase 5 remediation session

1. Install Voicebox on Windows — **DONE** (running at localhost:17493)
2. Download at least one TTS model (Qwen3-TTS recommended) via Voicebox UI
3. Create one test voice profile in Voicebox UI to verify workflow
4. Generate one test sentence to confirm CPU performance is tolerable
5. Note down: Voicebox URL, which models downloaded, which engines enabled

---

## Open questions for Phase 5 remediation session

1. Should Chorus use Voicebox's Stories API for chapter assembly, or keep ffmpeg?
2. Should Chorus adopt Voicebox's generation history, or keep its own segment state?
3. How does Chorus map its "regenerate" action — Voicebox's `/retry` vs `/regenerate` vs create new generation?
4. How should Chorus handle model loading on startup? (blocking wait, background load, on-demand)
5. Should Chorus detect Voicebox's port automatically (check common config locations) or require manual config?
6. Should voice profiles be created lazily (first time voice is used) or eagerly (when voice is added to library)?

---

## Revision history

**2026-04-19** — Initial remediation plan drafted after Voicebox v0.4.0 API inspection on Ben's Windows machine.
