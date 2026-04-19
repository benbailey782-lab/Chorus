# TTS Generation — User Guide

This guide walks through generating per-segment audio on a Mac with Voicebox
running. On Windows (or any machine with `VOICEBOX_ENABLED=false`), all of this
UI still renders but the Generate button degrades to a read-only explainer.

## Prerequisites

1. **Voicebox is installed and running on the Mac.** See
   `docs/VOICEBOX-WIRING.md` for the integration punchlist. Confirm:
   ```bash
   curl http://localhost:8090/        # or whatever VOICEBOX_BASE_URL points at
   curl http://localhost:8765/api/voicebox/status
   # → {"enabled": true, "reachable": true, ...}
   ```
2. **Voices exist in the Chorus Library with `voicebox_profile_id` populated.**
   Creating a voice with a reference audio file while `VOICEBOX_ENABLED=false`
   leaves `voicebox_profile_id` `NULL` — generation will fail for any character
   assigned that voice. When Voicebox is live, voices created (or
   reference-audio-replaced) through the UI get their profile id back-filled
   automatically.
3. **Attribution is complete for the target chapter.** Chapter Review shows
   per-chapter status; generate only after the chapter is `attributed`.
4. **Every speaking character has a voice assignment.** The Casting view
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
5. **Watch the progress bar.** Per-segment icons flip from `pending` →
   `generating` (spinner) → `generated` (waveform). Errors show a red `!`. The
   pipeline uses one in-flight generation at a time by default
   (`voicebox_max_concurrent_generations = 1`).
6. **Listen and act per segment.** Open the Detail Panel (tap a segment). The
   **Audio** section exposes:
   - **Play** — stream the raw file from disk.
   - **Regenerate** — wipe both raw and approved files and re-enqueue.
   - **Approve** — stamp `segments.approved_at` and copy the raw file under
     `audio/approved/`. The source file is preserved.
   - **Reject** — clear `segments.approved_at` only; the file stays on disk.
7. **Bulk actions.** Select multiple segments and use
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
