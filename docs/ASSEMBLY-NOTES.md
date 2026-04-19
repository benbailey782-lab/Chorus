# Assembly Notes

Technical reference for the Phase 6 chapter-assembly pipeline. The user-facing story is in `docs/PLAYER-GUIDE.md`.

## Prerequisite: ffmpeg on PATH

Chorus uses the system `ffmpeg` / `ffprobe` binaries. They must be on `PATH`.

- **Windows:** `choco install ffmpeg` (Chocolatey) or `winget install Gyan.FFmpeg`.
- **Mac:** `brew install ffmpeg`.

If ffmpeg is not installed, `assemble_chapter` raises `FfmpegMissingError` and the direct-mode job fails with a clear `"ffmpeg not found on PATH"` message. No silent fallback — fail loudly so the operator installs it.

## Windows: ProactorEventLoop required

- **Symptom:** assembly jobs fail with `NotImplementedError` from `base_events._make_subprocess_transport`.
- **Cause:** Python's default `SelectorEventLoop` on Windows does not support `asyncio.create_subprocess_exec` (used to invoke ffmpeg/ffprobe).
- **Fix:** use `scripts/serve.py` as the entry point. It sets `asyncio.WindowsProactorEventLoopPolicy()` **before** `import uvicorn` and passes `loop="asyncio"` to `uvicorn.run()`. `scripts/run.bat` and `scripts/run.sh` both invoke it.
- **Do NOT run `uvicorn backend.main:app --reload` directly on Windows.** Uvicorn creates the event loop before `backend.main` imports, so the policy switch inside that module arrives too late. The error reappears even with the module-level guard.
- `backend/main.py` keeps a defensive policy switch too, which is a safety net for non-Windows platforms and any future consumer that imports `backend.main` before the loop starts. Harmless when redundant.
- **Mac/Linux:** no asyncio limitation — `SelectorEventLoop` supports subprocess on those platforms. `scripts/serve.py` still works identically; the policy swap is a no-op there.
- **Operator action:** use `scripts/run.bat` (Windows) or `scripts/run.sh` (Mac/Linux) as documented in the README. No manual configuration required.

## Pipeline

1. **Load segments** — ordered by `order_index` for the chapter.
2. **Check for missing segments** — any segment where `audio_path IS NULL`, the file is not on disk, or `status IN ('pending','generating','error')`. If missing: raise `AssemblyIncompleteError` carrying the list of offending segment IDs. The API surfaces these via `GET /assembly-status.missing_segments[]` and the Player shows the "Chapter incomplete" dialog.
3. **Compute `segment_hash`** — SHA-256 of sorted tuples `(segment_id, updated_at, audio_path, approved_at)`. This is the cache invalidation key. Any change to any of those four fields across the chapter's segments produces a different hash.
4. **Cache check** — read the `chapter_assemblies` row (if any). If `segment_hash` matches current AND the cached WAV still exists on disk: return `AssemblyResult(from_cache=True, ...)` and skip ffmpeg entirely.
5. **Write concat list** — `data/projects/<project_id>/audio/assembled/<chapter_id>.concat.txt`, one line per segment:
   ```
   file '<absolute-path-to-segment>.wav'
   ```
6. **Invoke ffmpeg:**
   ```
   ffmpeg -y -f concat -safe 0 -i <concat.txt> -c:a pcm_s16le -ar 44100 -ac 1 <output.wav>
   ```
   Canonical mono 16-bit PCM at 44.1 kHz. Robust against mixed input formats — one transcode pass, lossless for WAV sources.
7. **Probe duration:**
   ```
   ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 <output.wav>
   ```
   Parse float seconds → round to integer milliseconds.
8. **Upsert `chapter_assemblies`** — one row per chapter, holds `audio_path`, `duration_ms`, `segment_hash`, `created_at`.
9. **Delete the concat list** — no longer needed.
10. **Return** `AssemblyResult(chapter_id, audio_path, duration_ms, segment_hash, from_cache=False)`.

## Cache invalidation

Invalidation is **forward-looking**: any state change that *will* affect a chapter's audio invalidates the cached assembly immediately, even before the new audio lands. Next play re-assembles.

Hook sites (in Phase 5's `backend/api/generation.py`):

- `POST /api/segments/{id}/generate` — forward-looking: the assembly is about to be stale.
- `POST /api/segments/{id}/regenerate`
- `POST /api/segments/{id}/approve` — `segment_hash` includes `approved_at`, so approve alone is enough to invalidate.
- `POST /api/segments/{id}/reject`
- Inside the `handle_generate_segment` direct-handler, after the successful write.

The placeholder script (`scripts/generate_placeholder_audio.py`) also invalidates per chapter after writing its silent WAVs.

The invalidation helper:

1. Deletes the cached WAV from disk (best-effort, ignores `FileNotFoundError`).
2. Deletes the `chapter_assemblies` row.

**Never raises** — invalidation is a best-effort side effect; the calling request must not fail if the cache is already gone.

## Concurrency

A module-level `asyncio.Semaphore(1)` serializes ffmpeg invocations. Only one assembly runs at a time, backend-wide.

**Future:** bump via a `settings.assembly_max_concurrent` field once we confirm the Mac hardware can run multiple ffmpeg processes without CPU / disk-IO contention. On Windows dev the bottleneck is usually the disk, so serial is the safe default.

## Endpoints reference

All live in `backend/api/assembly.py` (mounted under `/api`).

### `POST /api/chapters/{id}/assemble?force=false`

Kicks off assembly. Short-circuits when the cache is valid (returns `from_cache=True, job_id=null`).

Response:
```json
{ "chapter_id": "...", "job_id": "...", "from_cache": false }
```

With `?force=true`, bypass the cache check and re-assemble unconditionally.

### `GET /api/chapters/{id}/assembly-status`

Poll while assembling. Returns:

```json
{
  "ready": true,
  "duration_ms": 184532,
  "assembling": false,
  "progress": 100,
  "from_cache": false,
  "hash": "sha256:...",
  "missing_segments": []
}
```

Progress reports **20 / 60 / 90 / 100** at:

- 20 — concat list written.
- 60 — ffmpeg done.
- 90 — ffprobe done.
- 100 — row upserted.

### `GET /api/chapters/{id}/audio`

`FileResponse(media_type="audio/wav")`. Streams the cached assembled file.

Strict **404** if no `chapter_assemblies` row exists or the file is missing on disk. **No side effects** — this endpoint never triggers assembly; it's a dumb file server.

### `GET /api/chapters/{id}/segment-timings`

List of per-segment timing rows for the synced-text view:

```json
[
  { "segment_id": "...", "order_index": 0, "start_ms": 0, "end_ms": 3812,
    "duration_ms": 3812, "speaker_name": "Bran", "text_preview": "..." },
  ...
]
```

Cumulative sum of `segments.duration_ms`. `text_preview` truncates at ~80 chars.

## Drift caveat

`segment-timings` are derived from the cumulative sum of `segments.duration_ms`, **not** from the assembled WAV itself. If ffmpeg concat introduces any drift — e.g., re-encoded segments have a slightly different sample count than their original metadata reports — the timings could lag by tens of milliseconds across a long chapter.

Phase 7 can refine by reading actual segment boundaries from the assembled file (ffprobe `-show_packets` or `-show_frames` + a boundary-detection pass, or writing per-segment markers during concat).

## File layout

```
data/projects/<project_id>/audio/
  raw/<chapter_id>/segment_<segment_id>.<ext>         (from generation or placeholder)
  approved/<chapter_id>/segment_<segment_id>.<ext>    (copy on approve)
  assembled/<chapter_id>.wav                          (assembly cache)
```

The `assembled/` directory is a pure cache. It's gitignored via the top-level `data/` rule; invalidation deletes files freely; a fresh `rm -rf data/projects/<id>/audio/assembled/` followed by `DELETE FROM chapter_assemblies WHERE ...` is a valid nuclear option with no data loss beyond the cache.

## Stale failed jobs

Phase 6 shipped with a Windows-specific asyncio bug (default `SelectorEventLoop` doesn't support `asyncio.create_subprocess_exec`). This was fixed in phase6-fix / phase6-fix3 by setting `WindowsProactorEventLoopPolicy` in both `backend/main.py` and `backend/main_serve.py`, but the failed `assemble_chapter` rows from before the fix remain in the `jobs` table.

To keep those old rows from cluttering the per-project PendingJobsBanner, **`GET /api/projects/{id_or_slug}/jobs` hides failed `assemble_chapter` jobs older than 5 minutes by default** (implemented in `backend/api/jobs.py::list_project_jobs`). Live failures (<5 min old) still surface so real problems aren't masked.

To see everything, including stale failures, for debug inspection:

```
GET /api/projects/<id_or_slug>/jobs?include_old_failures=true
```

The underlying rows are never auto-deleted — they remain in the `jobs` table indefinitely for post-mortem querying. If you want to purge them entirely:

```sql
DELETE FROM jobs
  WHERE kind = 'assemble_chapter'
    AND status = 'failed'
    AND datetime(updated_at) < datetime('now', '-5 minutes');
```

The filter uses lexical string comparison on the `updated_at` column. SQLite stores `datetime('now')` as `"YYYY-MM-DD HH:MM:SS"` UTC text, which sorts chronologically as a string, so no format conversion is required in Python — the threshold is computed as `datetime.now(timezone.utc) - 5min` and compared directly.
