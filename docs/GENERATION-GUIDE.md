# TTS Generation — User Guide

This guide walks through generating per-segment audio against a live Voicebox
instance (Windows or Mac — Voicebox v0.4.0 supports both). When
`voicebox_enabled` is `false` or no URL is configured, all of this UI still
renders but the Generate button degrades to a read-only explainer.

## First-time setup

Voicebox runs at a runtime-assigned port (e.g. `localhost:17493`) and is **not**
auto-discovered. One-time setup:

1. Install and start Voicebox (<https://github.com/jamiepine/voicebox>); read
   the bound port from its UI.
2. In Chorus open **Settings → Voicebox**. Paste the full base URL into the
   URL field and click **Test connection** — a green confirmation means
   Chorus can reach the API.
3. Tick **Enable** and click **Save**. The change is persisted to
   `data/voicebox_config.json` and applied on the next request — **no backend
   restart required**.
4. Add at least one TTS model from inside the Voicebox UI (Qwen3-TTS is the
   recommended default). Chorus will lazy-load whatever model a voice's
   engine requires on first use.

See `docs/VOICEBOX-WIRING.md` for the full reference (config persistence,
exception hierarchy, endpoint table, lazy-loading internals).

## Prerequisites

1. **Voicebox configured and reachable.** Verify via Settings → Voicebox →
   Test connection, or:
   ```bash
   curl http://localhost:8765/api/voicebox/status
   # → {"enabled": true, "reachable": true, "base_url": "...", ...}
   ```
2. **Voices exist in the Chorus Library with `voicebox_profile_id` populated.**
   Voices are now created **eagerly** in Voicebox the moment they're saved in
   Chorus (Phase 5R) — but a voice created while Voicebox was unreachable
   will land with `voicebox_profile_id IS NULL` and a "Needs sync" badge on
   its card. Click the badge to retry; the backend re-runs the
   `create_profile` + `add_sample_to_profile` calls.
3. **Each voice picks its engine at creation time.** The VoiceEditor's
   engine dropdown writes `voicebox_engine` (default `qwen3-tts`). Changing
   engine on an existing voice deletes + recreates its Voicebox profile and
   requires regeneration of any existing audio assigned to it.
4. **Attribution is complete for the target chapter.** Chapter Review shows
   per-chapter status; generate only after the chapter is `attributed`.
5. **Every speaking character has a voice assignment.** The Casting view
   enforces this — a character without an assignment will cause "No voice
   resolved" errors at generation time.

## Happy path

1. **Verify Voicebox health.**
   - In the header/banner of Chapter Review, the Voicebox chip should read
     "Voicebox ready". If it reads "Voicebox disabled" or
     "Voicebox unreachable", stop here and fix the underlying issue.
   - You can also call `GET /api/voicebox/status` directly to debug.
2. **Open Chapter Review** for a chapter:
   `/project/<idOrSlug>/chapters/<chapterId>`.
3. **Click "Generate (N)" in the toolbar.** `N` is the number of segments that
   currently have no audio (`status = "pending"` or `"error"`). The button is
   styled:
   - `btn-primary` when Voicebox is ready and `N > 0`.
   - `btn-surface` when Voicebox is unreachable (still clickable to see the
     estimate modal, which will explain why generation is blocked).
   - `disabled` when `N == 0`.
4. **Review the estimate modal.** It shows segment count, estimated wall time
   (driven by `voicebox_default_wps = 2.5`), and any blocking issues
   (characters without voices, voices without profiles). Click **Generate** to
   enqueue.
5. **First generation per engine triggers model load.** A global
   ModelLoadingBanner shows progress (e.g. `Loading qwen-tts-1.7B… 47%`).
   First-time loads typically take 2–4 minutes; subsequent generations of
   the same engine are immediate (model cached in Voicebox + flagged in the
   backend's in-process loader cache).
6. **Watch the progress bar.** Per-segment icons flip from `pending` →
   `generating` (spinner) → `generated` (waveform). Errors show a red `!`. The
   pipeline uses one in-flight generation at a time by default
   (`voicebox_max_concurrent_generations = 1`).
7. **Listen and act per segment.** Open the Detail Panel (tap a segment). The
   **Audio** section exposes:
   - **Play** — stream the raw file from disk.
   - **Regenerate** — routes through Voicebox's
     `POST /generate/{id}/regenerate` when the segment has a stored
     `voicebox_generation_id` (reuses original profile + engine state on
     the Voicebox side); falls back to a fresh generate when the generation
     id is missing. Wipes both raw and approved files first.
   - **Retry** — only shown for segments with `status='error'`. Routes
     through `POST /generate/{id}/retry` when a prior generation id exists.
   - **Approve** — stamp `segments.approved_at` and copy the raw file under
     `audio/approved/`. The source file is preserved.
   - **Reject** — clear `segments.approved_at` only; the file stays on disk.
   - The truncated `voicebox_generation_id` shows above the buttons for
     debugging — copy it to look up the generation in Voicebox's UI.
8. **Bulk actions.** Select multiple segments and use
   **Approve selected** / **Regenerate selected** from the bulk actions menu.

## File layout

Audio is written under the project's data directory. Paths:

```
data/projects/<project_id>/audio/raw/<chapter_id>/segment_<segment_id>.<ext>
data/projects/<project_id>/audio/approved/<chapter_id>/segment_<segment_id>.<ext>
```

`<ext>` is sniffed from the `Content-Type` header Voicebox returns
(`audio/wav` → `.wav`, `audio/mpeg` → `.mp3`, `audio/flac` → `.flac`,
`audio/ogg` → `.ogg`). Unknown types fall back to `.wav` with a warning log.

Assembly (Phase 8) prefers `approved/` when present and falls back to `raw/`
only when explicitly configured.

## Failure triage

### Single segment shows `error`

1. Hover the `!` icon for a summary; open the Detail Panel for the full
   error string.
2. `GET /api/jobs/<job_id>` has the raw exception message from the backend.
3. Common causes:
   - `VoiceboxGenerationFailed` — Voicebox itself returned `status = "error"`.
     Check Voicebox logs; often a text/profile mismatch.
   - `VoiceboxUnreachableError` — transient network blip. Regenerate once.
   - `No voice resolved` — the segment's character has no voice, or the
     assigned voice has no `voicebox_profile_id`. Fix in Casting.

### Voicebox goes down mid-run

Any generations already in flight will fail with `VoiceboxUnreachableError`
and flip to `status = "error"`. Completed segments are unaffected. Bring
Voicebox back up, then click **Generate (N)** again — only the failed segments
will re-enqueue (the button counts `pending` + `error`).

### "No voice resolved"

Open the character in Casting, assign a voice that has a `voicebox_profile_id`.
If your voice library entries predate a live Voicebox run, you may need to
re-upload the reference audio to trigger profile creation.

## Per-segment actions — reference

Exposed in the Detail Panel (Audio section) and on bulk toolbars. All routes
defined in `backend/api/generate.py`:

| Action      | Route                                 | Side effect                                        |
|---|---|---|
| Generate    | `POST /api/segments/<id>/generate`    | Enqueues `generate_segment` job (direct mode).     |
| Regenerate  | `POST /api/segments/<id>/regenerate`  | Wipes raw + approved files; re-enqueues.           |
| Approve     | `POST /api/segments/<id>/approve`     | Copies `raw/…` → `approved/…`; stamps `approved_at`.|
| Reject      | `POST /api/segments/<id>/reject`      | Clears `approved_at`. File unchanged.              |
| Play raw    | `GET /api/segments/<id>/audio?kind=raw` | Streams the raw file.                           |
| Play approved | `GET /api/segments/<id>/audio?kind=approved` | Streams the approved file.                 |

Bulk endpoints accept a JSON body of `{segment_ids: [...]}`.

## Windows dev aid: placeholder audio

**This is a temporary dev-only tool.** It exists so Phase 6 player UI work
(playback sync, scrubber, chapter progression, timing) can be exercised on
Windows where Voicebox is not available. Do **not** add it to production setup
docs, and do **not** rely on its output for listening — every segment is silent.

### Purpose

`scripts/generate_placeholder_audio.py` walks every segment in a project (or a
single chapter) and writes a silent PCM-16 mono WAV whose duration is the
estimated per-segment length (`word_count / voicebox_default_wps`, clamped to
1-30 s). It then updates each segment row exactly like the real generation
pipeline does — `audio_path`, `duration_ms`, `status='generated'`,
`approved_at` left NULL — so the player, assembler, approval toolbar, and all
Phase 5/6 UI can reach their post-generation code paths.

Files land in the same directory the real generator uses:

    data/projects/<project_id>/audio/raw/<chapter_id>/segment_<segment_id>.wav

That means when Voicebox comes online on the Mac and real generation runs,
`regenerate` / `generate (N)` will simply overwrite these WAVs — no cleanup
required.

### Prerequisites

- `ffmpeg` on `PATH` (`winget install ffmpeg`, `scoop install ffmpeg`, or
  `brew install ffmpeg`). The script exits 2 with install hints if missing.
- The project venv activated so `backend.*` imports resolve.

### Usage

```bash
# Dry-run — lists every segment, writes nothing, no DB changes.
python scripts/generate_placeholder_audio.py --project agot-chapter-1-real-test --dry-run

# Generate placeholders for every chapter in a project.
python scripts/generate_placeholder_audio.py --project agot-chapter-1-real-test

# Scope to a single chapter (by id or by exact title, case-insensitive).
python scripts/generate_placeholder_audio.py --project agot-chapter-1-real-test --chapter BRAN

# Force overwrite of existing files (default is skip).
python scripts/generate_placeholder_audio.py --project agot-chapter-1-real-test --force

# Override the words-per-second factor (default comes from settings).
python scripts/generate_placeholder_audio.py --project agot-chapter-1-real-test --wps 2.0
```

`--project` accepts either a project UUID or its slug. `--chapter` accepts
either a chapter UUID or its exact title (ambiguous titles exit 2 with the
conflicting rows listed so you can pick by id).

### What it writes

- **File**: silent WAV at `data/projects/<id>/audio/raw/<chapter_id>/segment_<seg_id>.wav`,
  sized to the estimated duration.
- **DB**: `UPDATE segments SET audio_path=<relative>, duration_ms=<int>,
  status='generated', updated_at=now`. `approved_at` stays NULL — the real
  generation path is the only thing that should flip segments to `approved`.
- **Cache**: calls `invalidate_chapter_cache(chapter_id)` after each chapter
  so any stale `chapter_assemblies` row is dropped.

### What it does **not** do

- Does not touch `approved/` files.
- Does not change project or chapter status.
- Does not flip `segments.text_modified`.
- Does not attempt to mimic Voicebox audio quality — silence only.

