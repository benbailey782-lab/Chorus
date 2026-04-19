"""Chapter assembly: concat per-segment audio into a single WAV (Phase 6, §9.7).

Pipeline:
  1. Hash the current ordered set of segments for cache lookup.
  2. If a ``chapter_assemblies`` row already matches the hash AND the file
     exists on disk, return ``from_cache=True`` without touching ffmpeg.
  3. Otherwise enumerate the segments, write an ffmpeg concat-demuxer input
     file, invoke ffmpeg to transcode → canonical mono 16-bit PCM / 44.1 kHz,
     probe the resulting duration, and upsert the assemblies row.

Design notes:
  * Uses ``asyncio.create_subprocess_exec`` so we never block the event loop.
  * A module-level ``asyncio.Semaphore(1)`` serializes ffmpeg invocations —
    concat is CPU-heavy and running two chapters in parallel on a laptop
    stalls the API. Forward-compat: bump when we ship a real machine.
  * Raw segment files are the source of truth even after approval. Approved
    is a separate "gate" for Phase 7 — see decision 6 in the brief; the
    player plays whatever has been generated.
  * Progress tracking is advisory: the direct-mode handler writes intermediate
    progress values (20 → 60 → 90 → 100) via ``repo.set_status`` so the UI can
    render a progress bar while ffmpeg is still running. It's not fine-grained
    within the ffmpeg process itself (ffmpeg progress via ``-progress`` pipe
    is feasible but not worth the complexity for v1 — most chapters assemble
    in under 2s).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from backend.audio import paths as audio_paths
from backend.db import connect
from backend.jobs import repo, worker

log = logging.getLogger(__name__)

JOB_KIND = "assemble_chapter"

# FFmpeg canonical output: mono 16-bit PCM at 44.1kHz. Gives a deterministic
# byte-for-byte output across runs and sidesteps mixed-input-format issues.
FFMPEG_CODEC = "pcm_s16le"
FFMPEG_SAMPLE_RATE = "44100"
FFMPEG_CHANNELS = "1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AssemblyError(Exception):
    """Base class for chapter-assembly failures."""


class AssemblyIncompleteError(AssemblyError):
    """Raised when one or more segments are missing audio.

    Caller (the API layer or direct-mode handler) can read
    ``missing_segment_ids`` to surface the exact list to the user.
    """

    def __init__(self, missing_segment_ids: list[str]):
        self.missing_segment_ids = list(missing_segment_ids)
        super().__init__(
            f"Missing audio for {len(missing_segment_ids)} segments"
        )


class FfmpegMissingError(AssemblyError):
    """Raised when ``shutil.which('ffmpeg')`` returns None.

    Handler surfaces install instructions for Mac + Windows.
    """


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AssemblyResult:
    chapter_id: str
    audio_path: str       # repo-root-relative
    duration_ms: int
    segment_hash: str
    from_cache: bool
    segment_count: int


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

_sem: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Module-level serialization — one ffmpeg at a time."""
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)
    return _sem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_rel_path(abs_path: Path | str) -> str:
    """Return a repo-root-relative path string for DB storage.

    Mirrors :func:`backend.audio.generation._repo_rel_path` so the two modules
    store paths consistently.
    """
    p = Path(abs_path)
    try:
        root = Path(".").resolve()
        return str(p.resolve().relative_to(root))
    except ValueError:
        return str(p.resolve())


def _segment_rows(chapter_id: str, conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, chapter_id, audio_path, duration_ms, status,
               approved_at, updated_at, order_index
        FROM segments
        WHERE chapter_id = ?
        ORDER BY order_index
        """,
        (chapter_id,),
    ).fetchall()


def _chapter_project_id(chapter_id: str, conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT project_id FROM chapters WHERE id = ?", (chapter_id,)
    ).fetchone()
    return row["project_id"] if row else None


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def compute_segment_hash(
    chapter_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> str:
    """SHA-256 of (segment_id, updated_at, audio_path, approved_at) tuples.

    Hex digest (64 chars). Any segment edit, regeneration, or approval state
    change mutates ``updated_at``; any new audio-path changes ``audio_path``;
    approve/reject toggles ``approved_at``. All three are captured so the
    cache invalidates on every meaningful state change.

    Order-dependence comes from ``ORDER BY order_index`` in the select — two
    chapters with identical segments in different orders hash differently
    (as they should; ffmpeg would produce different audio).
    """

    def _do(c: sqlite3.Connection) -> str:
        rows = _segment_rows(chapter_id, c)
        h = hashlib.sha256()
        for r in rows:
            tup = "|".join(
                str(x) if x is not None else ""
                for x in (
                    r["id"],
                    r["updated_at"],
                    r["audio_path"],
                    r["approved_at"],
                )
            )
            h.update(tup.encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


def check_missing_segments(
    chapter_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> list[str]:
    """Return ids of segments that are not ready for assembly.

    A segment is "missing" if:
      * its ``audio_path`` is NULL or the file doesn't exist on disk, OR
      * its ``status`` is ``pending``, ``generating``, or ``error``.

    An ``approved`` segment with audio is considered ready (same as
    ``generated`` — approval does not affect assembly, per decision 6).
    """

    def _do(c: sqlite3.Connection) -> list[str]:
        rows = _segment_rows(chapter_id, c)
        missing: list[str] = []
        root = Path(".").resolve()
        for r in rows:
            status = r["status"]
            audio_path = r["audio_path"]
            if status in ("pending", "generating", "error"):
                missing.append(r["id"])
                continue
            if not audio_path:
                missing.append(r["id"])
                continue
            # audio_path is stored repo-root-relative; resolve and check.
            candidate = (root / audio_path).resolve()
            if not candidate.exists():
                missing.append(r["id"])
        return missing

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


# ---------------------------------------------------------------------------
# Concat list / ffmpeg
# ---------------------------------------------------------------------------


def _write_concat_list(
    list_path: Path, audio_paths_abs: list[Path]
) -> None:
    """Write the ffmpeg concat-demuxer input file.

    Format: one ``file '<path>'`` line per input. Single quotes are the
    concat-demuxer convention; embedded quotes must be escaped as ``'\\''``
    but raw segment filenames never contain quotes (they're
    ``segment_<uuid>.<ext>``), so we don't bother.
    """
    lines = [f"file '{str(p)}'" for p in audio_paths_abs]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run_ffmpeg_concat(
    concat_list: Path, output_wav: Path
) -> None:
    """Invoke ffmpeg to concat + transcode to canonical WAV.

    Equivalent to:
        ffmpeg -y -f concat -safe 0 -i concat.txt \
               -c:a pcm_s16le -ar 44100 -ac 1 output.wav
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c:a", FFMPEG_CODEC,
        "-ar", FFMPEG_SAMPLE_RATE,
        "-ac", FFMPEG_CHANNELS,
        str(output_wav),
    ]
    log.debug("ffmpeg concat: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace").strip()
        # Keep stderr output reasonably sized for the job row.
        if len(tail) > 2000:
            tail = "..." + tail[-2000:]
        raise AssemblyError(f"ffmpeg failed (rc={proc.returncode}): {tail}")


async def _probe_duration_ms(wav_path: Path) -> int:
    """Return the duration of ``wav_path`` in integer milliseconds.

    Uses ``ffprobe`` so we don't have to read the whole file. Rounds the
    float-seconds output via Python's ``round`` to nearest ms.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(wav_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise AssemblyError(f"ffprobe failed (rc={proc.returncode}): {tail}")
    text = (stdout or b"").decode("utf-8", errors="replace").strip()
    try:
        seconds = float(text)
    except ValueError as e:
        raise AssemblyError(f"ffprobe returned non-numeric duration: {text!r}") from e
    return int(round(seconds * 1000))


# ---------------------------------------------------------------------------
# Cache row upsert
# ---------------------------------------------------------------------------


def _upsert_assembly_row(
    *,
    chapter_id: str,
    audio_path_rel: str,
    duration_ms: int,
    segment_hash: str,
) -> dict[str, Any]:
    """Insert or update the ``chapter_assemblies`` row for this chapter.

    Preserves ``created_at`` on update; always bumps ``updated_at``.
    Returns the resulting row as a plain dict.
    """
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM chapter_assemblies WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE chapter_assemblies
                SET audio_path = ?, duration_ms = ?, segment_hash = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (audio_path_rel, duration_ms, segment_hash, existing["id"]),
            )
            row_id = existing["id"]
        else:
            row_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO chapter_assemblies
                    (id, chapter_id, audio_path, duration_ms, segment_hash,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (row_id, chapter_id, audio_path_rel, duration_ms, segment_hash),
            )
        row = conn.execute(
            "SELECT * FROM chapter_assemblies WHERE id = ?", (row_id,)
        ).fetchone()
        return dict(row)


# ---------------------------------------------------------------------------
# Public: invalidate
# ---------------------------------------------------------------------------


def invalidate_chapter_cache(
    chapter_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> bool:
    """Delete the assembled WAV (if present) + the chapter_assemblies row.

    Best-effort: logs at INFO but never raises. Returns True if anything was
    actually deleted. Safe to call on chapters that have no assembly yet.
    """

    def _do(c: sqlite3.Connection) -> bool:
        row = c.execute(
            "SELECT id, audio_path FROM chapter_assemblies WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()
        if not row:
            return False
        deleted_file = False
        audio_path = row["audio_path"]
        if audio_path:
            candidate = (Path(".").resolve() / audio_path).resolve()
            try:
                if candidate.exists():
                    candidate.unlink()
                    deleted_file = True
            except OSError as e:
                log.warning(
                    "invalidate_chapter_cache: failed to unlink %s: %s",
                    candidate, e,
                )
        c.execute(
            "DELETE FROM chapter_assemblies WHERE id = ?", (row["id"],)
        )
        log.info(
            "invalidate_chapter_cache: chapter %s (file_deleted=%s)",
            chapter_id, deleted_file,
        )
        return True

    try:
        if conn is not None:
            return _do(conn)
        with connect() as c:
            return _do(c)
    except Exception:  # noqa: BLE001 — cache invalidation never raises
        log.exception(
            "invalidate_chapter_cache(%s) swallowed unexpected error", chapter_id
        )
        return False


# ---------------------------------------------------------------------------
# Public: assemble
# ---------------------------------------------------------------------------


async def assemble_chapter(
    chapter_id: str, *, force: bool = False, job_id: Optional[str] = None
) -> AssemblyResult:
    """Concatenate every segment's audio into a single WAV for this chapter.

    Steps (see module docstring for big picture):
      1. Load chapter → project_id. 404-like error via AssemblyError.
      2. Compute current ``segment_hash``.
      3. Cache lookup: if hash matches existing row AND file exists, return
         ``from_cache=True``. ``force=True`` skips this.
      4. Check for missing segments → AssemblyIncompleteError.
      5. Verify ffmpeg is on PATH → FfmpegMissingError.
      6. Under the module-level concat semaphore:
         a. Write concat list.
         b. Run ffmpeg (canonical pcm_s16le / 44.1kHz / mono).
         c. Probe duration.
      7. Upsert ``chapter_assemblies`` row.
      8. Delete concat list. Return result.

    The ``job_id`` argument, if provided, is used to publish intermediate
    progress (20/60/90/100) via :func:`repo.set_status`. It's optional so the
    function can be called directly in tests without a job.
    """
    with connect() as conn:
        project_id = _chapter_project_id(chapter_id, conn)
        if project_id is None:
            raise AssemblyError(f"chapter {chapter_id!r} not found")
        seg_rows = _segment_rows(chapter_id, conn)
        if not seg_rows:
            raise AssemblyError(
                f"chapter {chapter_id!r} has no segments — attribute first"
            )
        segment_hash = compute_segment_hash(chapter_id, conn=conn)

    # --- Cache short-circuit -------------------------------------------------
    root = Path(".").resolve()
    output_wav = audio_paths.assembled_chapter_path(project_id, chapter_id)
    output_rel = _repo_rel_path(output_wav)

    if not force:
        with connect() as conn:
            row = conn.execute(
                "SELECT audio_path, duration_ms, segment_hash FROM chapter_assemblies "
                "WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchone()
        if row and row["segment_hash"] == segment_hash:
            cached_path = (root / row["audio_path"]).resolve()
            if cached_path.exists():
                log.info(
                    "assemble_chapter: cache hit for chapter %s (hash=%s)",
                    chapter_id, segment_hash[:12],
                )
                return AssemblyResult(
                    chapter_id=chapter_id,
                    audio_path=row["audio_path"],
                    duration_ms=int(row["duration_ms"]),
                    segment_hash=segment_hash,
                    from_cache=True,
                    segment_count=len(seg_rows),
                )

    # --- Completeness check --------------------------------------------------
    missing = check_missing_segments(chapter_id)
    if missing:
        raise AssemblyIncompleteError(missing)

    # --- ffmpeg preflight ----------------------------------------------------
    if shutil.which("ffmpeg") is None:
        raise FfmpegMissingError("ffmpeg not found on PATH")
    if shutil.which("ffprobe") is None:
        # ffprobe ships with ffmpeg on every mainstream install; treat as
        # equivalent so the user doesn't get a confusing second error.
        raise FfmpegMissingError("ffprobe not found on PATH")

    # --- Build ordered absolute input list ----------------------------------
    ordered_inputs: list[Path] = []
    for r in seg_rows:
        audio_rel = r["audio_path"]
        # check_missing_segments already guaranteed these are populated + present.
        ordered_inputs.append((root / audio_rel).resolve())

    concat_list = audio_paths.assembled_concat_list_path(project_id, chapter_id)

    async with _get_semaphore():
        _write_concat_list(concat_list, ordered_inputs)
        if job_id:
            try:
                repo.set_status(job_id, "running", progress=20.0,
                                message="concat list written")
            except Exception:  # noqa: BLE001
                log.debug("progress update (20) failed", exc_info=True)

        try:
            await _run_ffmpeg_concat(concat_list, output_wav)
        except Exception:
            # Best-effort cleanup of the concat list on failure so we don't
            # leave litter behind the next time we try.
            try:
                if concat_list.exists():
                    concat_list.unlink()
            except OSError:
                pass
            raise

        if job_id:
            try:
                repo.set_status(job_id, "running", progress=60.0,
                                message="ffmpeg done")
            except Exception:  # noqa: BLE001
                log.debug("progress update (60) failed", exc_info=True)

        duration_ms = await _probe_duration_ms(output_wav)
        if job_id:
            try:
                repo.set_status(job_id, "running", progress=90.0,
                                message="duration probed")
            except Exception:  # noqa: BLE001
                log.debug("progress update (90) failed", exc_info=True)

        _upsert_assembly_row(
            chapter_id=chapter_id,
            audio_path_rel=output_rel,
            duration_ms=duration_ms,
            segment_hash=segment_hash,
        )

        # Delete the concat list — it's a transient artifact.
        try:
            concat_list.unlink()
        except OSError as e:
            log.warning("failed to remove concat list %s: %s", concat_list, e)

    log.info(
        "assemble_chapter: chapter %s assembled %d segments → %s (%dms)",
        chapter_id, len(seg_rows), output_rel, duration_ms,
    )
    return AssemblyResult(
        chapter_id=chapter_id,
        audio_path=output_rel,
        duration_ms=duration_ms,
        segment_hash=segment_hash,
        from_cache=False,
        segment_count=len(seg_rows),
    )


# ---------------------------------------------------------------------------
# Public: trigger
# ---------------------------------------------------------------------------


async def trigger_assemble(
    chapter_id: str, *, force: bool = False
) -> tuple[str, bool]:
    """Enqueue an ``assemble_chapter`` job. Always creates the job row.

    Returns ``(job_id, from_cache_possible)``. ``from_cache_possible`` is True
    when we detected a matching cache row at trigger time — callers may use
    this as a UI hint but should still poll ``/assembly-status`` for the
    authoritative answer. The handler always runs ``assemble_chapter``, which
    returns quickly when the cache actually hits.
    """
    with connect() as conn:
        project_id = _chapter_project_id(chapter_id, conn)
        if project_id is None:
            raise AssemblyError(f"chapter {chapter_id!r} not found")
        current_hash = compute_segment_hash(chapter_id, conn=conn)
        row = conn.execute(
            "SELECT segment_hash, audio_path FROM chapter_assemblies "
            "WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()

    from_cache_possible = False
    if not force and row and row["segment_hash"] == current_hash:
        candidate = (Path(".").resolve() / row["audio_path"]).resolve()
        if candidate.exists():
            from_cache_possible = True

    job = repo.create_job(
        project_id=project_id,
        kind=JOB_KIND,
        payload={"chapter_id": chapter_id, "force": force},
        status="queued",
        message=f"Assemble chapter {chapter_id}",
    )
    return job["id"], from_cache_possible


# ---------------------------------------------------------------------------
# Direct job handler
# ---------------------------------------------------------------------------


@worker.register_handler(JOB_KIND, mode="direct")
async def handle_assemble_chapter(
    job: dict[str, Any], payload: Any
) -> None:
    """Direct-mode handler for ``assemble_chapter`` jobs.

    Payload: ``{"chapter_id": str, "force": bool}``.

    On ``AssemblyIncompleteError``: marks the job failed with an error
    message listing the missing segment ids (first 10, then "+N more").

    On ``FfmpegMissingError``: marks the job failed with platform install
    instructions so the user can fix it without reading docs.
    """
    job_id = job["id"]
    if not isinstance(payload, dict):
        repo.set_status(
            job_id, "failed",
            error=f"assemble_chapter job {job_id} has invalid payload {payload!r}",
        )
        return
    chapter_id = payload.get("chapter_id")
    if not chapter_id:
        repo.set_status(
            job_id, "failed",
            error=f"assemble_chapter job {job_id} payload missing chapter_id",
        )
        return
    force = bool(payload.get("force", False))

    try:
        result = await assemble_chapter(
            chapter_id, force=force, job_id=job_id,
        )
    except AssemblyIncompleteError as e:
        ids = e.missing_segment_ids
        head = ", ".join(ids[:10])
        more = f" (+{len(ids) - 10} more)" if len(ids) > 10 else ""
        repo.set_status(
            job_id, "failed",
            error=f"missing_segments: {head}{more}",
            message=f"assembly incomplete — {len(ids)} segments missing audio",
            result={"missing_segment_ids": ids},
        )
        log.info(
            "assemble_chapter job %s incomplete: %d missing", job_id, len(ids)
        )
        return
    except FfmpegMissingError:
        repo.set_status(
            job_id, "failed",
            error=(
                "ffmpeg not found on PATH. Install via `brew install ffmpeg` "
                "on Mac or Chocolatey `choco install ffmpeg` on Windows."
            ),
        )
        return
    except AssemblyError as e:
        repo.set_status(job_id, "failed", error=f"{type(e).__name__}: {e}")
        log.warning("assemble_chapter job %s failed: %s", job_id, e)
        return

    repo.set_status(
        job_id,
        "complete",
        progress=100.0,
        result={
            "chapter_id": result.chapter_id,
            "audio_path": result.audio_path,
            "duration_ms": result.duration_ms,
            "segment_hash": result.segment_hash,
            "from_cache": result.from_cache,
            "segment_count": result.segment_count,
        },
        message=(
            f"assembled {result.segment_count} segments "
            f"({result.duration_ms}ms) — "
            f"{'cache hit' if result.from_cache else 'rebuilt'}"
        ),
    )
