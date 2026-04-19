"""Chapter-assembly HTTP surface (Phase 6, §9.7).

Four endpoints:
  * ``POST /api/chapters/{id}/assemble`` — enqueue an assembly job
    (or short-circuit with from_cache=True when the cache already matches).
  * ``GET  /api/chapters/{id}/assembly-status`` — snapshot the review/player
    UI polls while assembly is in flight.
  * ``GET  /api/chapters/{id}/audio`` — stream the assembled WAV via
    :class:`FileResponse` (FastAPI handles HTTP Range automatically).
  * ``GET  /api/chapters/{id}/segment-timings`` — ordered timeline metadata
    the player uses to highlight the current segment + render a scrub strip.

Job progress convention (advisory, written by the direct-mode handler):
  * ``20`` — concat list written
  * ``60`` — ffmpeg finished
  * ``90`` — duration probed
  * ``100`` — row upserted
The status endpoint surfaces the live ``progress`` value so the UI can
render a proportional bar without inventing its own heuristic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.audio import assembly
from backend.config import get_settings
from backend.db import connect
from backend.schemas import (
    AssemblyStatusOut,
    AssemblyTriggerOut,
    SegmentTimingOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["assembly"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_preview(text: str, limit: int = 80) -> str:
    """First ``limit`` chars with a trailing ellipsis when truncated."""
    if not text:
        return ""
    # Collapse internal whitespace so multi-line segments preview cleanly.
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: max(limit - 1, 1)] + "\u2026"


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def _require_chapter(chapter_id: str) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"chapter {chapter_id!r} not found")


# ---------------------------------------------------------------------------
# POST /chapters/{id}/assemble
# ---------------------------------------------------------------------------


@router.post(
    "/chapters/{chapter_id}/assemble",
    response_model=AssemblyTriggerOut,
    status_code=202,
)
async def assemble(chapter_id: str, force: bool = False) -> AssemblyTriggerOut:
    """Kick off an ``assemble_chapter`` job — or short-circuit to cache.

    When ``force=False`` AND a ``chapter_assemblies`` row exists with a hash
    matching the current segments AND the assembled file is present on disk,
    we skip creating a job and return ``from_cache=True`` with ``job_id=None``.
    Otherwise we create a queued job for the direct-mode worker.
    """
    _require_chapter(chapter_id)
    try:
        with connect() as conn:
            current_hash = assembly.compute_segment_hash(chapter_id, conn=conn)
            row = conn.execute(
                "SELECT segment_hash, audio_path FROM chapter_assemblies "
                "WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchone()

        if not force and row and row["segment_hash"] == current_hash:
            candidate = (
                Path(".").resolve() / row["audio_path"]
            ).resolve()
            if candidate.exists():
                return AssemblyTriggerOut(
                    chapter_id=chapter_id,
                    job_id=None,
                    from_cache=True,
                )

        job_id, _ = await assembly.trigger_assemble(chapter_id, force=force)
    except assembly.AssemblyError as e:
        raise HTTPException(400, str(e)) from e

    return AssemblyTriggerOut(
        chapter_id=chapter_id,
        job_id=job_id,
        from_cache=False,
    )


# ---------------------------------------------------------------------------
# GET /chapters/{id}/assembly-status
# ---------------------------------------------------------------------------


@router.get(
    "/chapters/{chapter_id}/assembly-status",
    response_model=AssemblyStatusOut,
)
def assembly_status(chapter_id: str) -> AssemblyStatusOut:
    """Snapshot for the player UI.

    * ``ready`` — cache row hash matches live segment hash AND file exists.
    * ``assembling`` — a queued/running ``assemble_chapter`` job exists for
      this chapter id.
    * ``progress`` — forwarded from the in-flight job's progress field
      (0–100). When idle, reports 100 if ready else 0.
    * ``missing_segments`` — segment ids blocking assembly. When ``ready`` is
      True this is always empty.
    """
    _require_chapter(chapter_id)
    root = Path(".").resolve()
    with connect() as conn:
        current_hash = assembly.compute_segment_hash(chapter_id, conn=conn)
        row = conn.execute(
            "SELECT segment_hash, audio_path, duration_ms FROM chapter_assemblies "
            "WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()

        ready = False
        duration_ms: Optional[int] = None
        from_cache = False
        if row and row["segment_hash"] == current_hash:
            candidate = (root / row["audio_path"]).resolve()
            if candidate.exists():
                ready = True
                from_cache = True
                duration_ms = int(row["duration_ms"]) if row["duration_ms"] is not None else None

        # Any in-flight assemble_chapter job for this chapter.
        in_flight = None
        job_rows = conn.execute(
            """
            SELECT id, status, progress, payload_json FROM jobs
            WHERE kind = 'assemble_chapter'
              AND status IN ('queued', 'running')
            ORDER BY datetime(created_at) DESC
            """
        ).fetchall()
        for jr in job_rows:
            try:
                pl = json.loads(jr["payload_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if pl.get("chapter_id") == chapter_id:
                in_flight = jr
                break

    assembling = in_flight is not None
    if assembling:
        raw_progress = in_flight["progress"] or 0.0
        try:
            progress = int(round(float(raw_progress)))
        except (TypeError, ValueError):
            progress = 0
    else:
        progress = 100 if ready else 0

    missing = [] if ready else assembly.check_missing_segments(chapter_id)

    return AssemblyStatusOut(
        chapter_id=chapter_id,
        ready=ready,
        duration_ms=duration_ms,
        assembling=assembling,
        progress=progress,
        from_cache=from_cache,
        hash=current_hash,
        missing_segments=missing,
    )


# ---------------------------------------------------------------------------
# GET /chapters/{id}/audio
# ---------------------------------------------------------------------------


@router.get("/chapters/{chapter_id}/audio")
def stream_chapter_audio(chapter_id: str) -> FileResponse:
    """Stream the assembled chapter WAV.

    Strict 404 when the ``chapter_assemblies`` row is missing or the file is
    gone from disk — the caller should POST to ``/assemble`` first and poll
    ``/assembly-status``. FastAPI's :class:`FileResponse` handles HTTP
    Range requests automatically when wrapping a real path.
    """
    _require_chapter(chapter_id)
    with connect() as conn:
        row = conn.execute(
            "SELECT audio_path FROM chapter_assemblies WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "no assembled audio for chapter")
    audio_rel = row["audio_path"]
    if not audio_rel:
        raise HTTPException(404, "assembly row has no audio_path")
    candidate = (Path(".").resolve() / audio_rel).resolve()
    if not candidate.exists():
        raise HTTPException(
            404,
            "assembled audio file is missing on disk — reassemble the chapter",
        )
    return FileResponse(
        candidate,
        media_type="audio/wav",
        filename=candidate.name,
    )


# ---------------------------------------------------------------------------
# GET /chapters/{id}/segment-timings
# ---------------------------------------------------------------------------


@router.get(
    "/chapters/{chapter_id}/segment-timings",
    response_model=list[SegmentTimingOut],
)
def segment_timings(chapter_id: str) -> list[SegmentTimingOut]:
    """Cumulative timeline for the player's scrub UI.

    ``start_ms`` / ``end_ms`` are derived by running-sum over each segment's
    ``duration_ms``. When a segment has no ``duration_ms`` (pending or
    still-generating), we substitute an estimate based on word count and
    ``settings.voicebox_default_wps``.

    Known limitation: ffmpeg concat can introduce sub-millisecond offsets
    between adjacent inputs (especially on mixed sample rates), so the sum of
    per-segment durations may drift 10–50ms from the assembled file's
    duration over a long chapter. Phase 7 can refine this by actually probing
    the assembled stream with ``ffprobe -show_packets`` and segmenting.
    """
    _require_chapter(chapter_id)
    wps = float(get_settings().voicebox_default_wps)

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.order_index, s.text, s.duration_ms, s.character_id,
                   c.name AS speaker_name
            FROM segments s
            LEFT JOIN characters c ON s.character_id = c.id
            WHERE s.chapter_id = ?
            ORDER BY s.order_index
            """,
            (chapter_id,),
        ).fetchall()

    out: list[SegmentTimingOut] = []
    cursor_ms = 0
    for r in rows:
        dur = r["duration_ms"]
        if dur is None or dur <= 0:
            words = _word_count(r["text"])
            if wps > 0 and words > 0:
                dur = int(round((words / wps) * 1000))
            else:
                dur = 0
        else:
            dur = int(dur)
        start_ms = cursor_ms
        end_ms = start_ms + dur
        cursor_ms = end_ms
        out.append(
            SegmentTimingOut(
                segment_id=r["id"],
                order_index=int(r["order_index"]),
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=dur,
                speaker_name=r["speaker_name"],
                text_preview=_truncate_preview(r["text"] or ""),
            )
        )
    return out
