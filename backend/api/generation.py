"""Audio generation API (Phase 5, §10.5 + §16).

Thin HTTP layer around :mod:`backend.audio.generation`. Eight mutating
endpoints + two read-only status/estimate endpoints that the review UI
polls.

Ownership model:
  * Segment lifecycle state (``pending → generating → generated → approved``)
    lives entirely on the ``segments`` row. The API just exposes it.
  * Job rows are created synchronously; the worker picks them up in the
    background. Clients treat the returned ``job_id`` as a polling handle
    against ``/api/jobs/{id}``.
  * ``approve`` copies raw → approved via ``shutil.copy2`` (timestamps
    preserved). ``reject`` clears ``approved_at`` but never touches files.
  * Streaming endpoints use :class:`FileResponse` so FastAPI sends a
    properly-terminated response even on partial reads / range requests.
"""

from __future__ import annotations

import datetime
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.audio import generation, paths as audio_paths
from backend.db import connect
from backend.schemas import (
    ChapterGenerationStatusOut,
    ChapterGenerationTriggerOut,
    GenerationEstimateOut,
    GenerationTriggerOut,
    SegmentOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso_z() -> str:
    """ISO-8601 UTC timestamp with trailing Z (spec's preferred form)."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _segment_context(segment_id: str) -> tuple[str, str]:
    """Return ``(project_id, chapter_id)``; 404 if the segment is gone."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.project_id AS project_id, s.chapter_id AS chapter_id
            FROM segments s JOIN chapters c ON s.chapter_id = c.id
            WHERE s.id = ?
            """,
            (segment_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, f"segment {segment_id!r} not found")
    return row["project_id"], row["chapter_id"]


def _segment_out(segment_id: str) -> SegmentOut:
    """Load a segment as :class:`SegmentOut`. Reuses the segments API logic
    so the UI gets an identical shape from both endpoints."""
    from backend.api.segments import _segment_to_out  # local import avoids cycle

    return _segment_to_out(segment_id)


def _resolve_existing_audio(
    glob_fn, project_id: str, chapter_id: str, segment_id: str
) -> Optional[Path]:
    """Return the first file matching the ``segment_<id>.*`` glob or None."""
    matches = glob_fn(project_id, chapter_id, segment_id)
    if not matches:
        return None
    # Deterministic pick — if somehow both .wav and .mp3 exist, prefer .wav
    # first (Voicebox's most common output).
    matches.sort(key=lambda p: (p.suffix.lstrip(".").lower() != "wav", p.name))
    return matches[0]


# ---------------------------------------------------------------------------
# Segment-level trigger endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/segments/{segment_id}/generate",
    response_model=GenerationTriggerOut,
    status_code=202,
)
async def generate_segment_endpoint(segment_id: str) -> GenerationTriggerOut:
    """Enqueue a fresh ``generate_segment`` job. Idempotent at the
    segment-status level — the handler itself short-circuits when audio
    already exists, so repeated calls are harmless but create extra job rows.

    Use :meth:`regenerate_segment_endpoint` instead to *force* re-synthesis.
    """
    _, chapter_id = _segment_context(segment_id)  # 404 if missing
    try:
        result = await generation.trigger_segment(segment_id, force=False)
    except generation.GenerationError as e:
        raise HTTPException(400, str(e)) from e
    # A new generation invalidates any cached chapter assembly. Late import
    # keeps the generation<->assembly dependency one-way.
    from backend.audio import assembly  # noqa: WPS433 — intentional late import
    assembly.invalidate_chapter_cache(chapter_id)
    return GenerationTriggerOut(
        job_id=result.job_id, estimated_seconds=result.estimated_seconds
    )


@router.post(
    "/segments/{segment_id}/regenerate",
    response_model=GenerationTriggerOut,
    status_code=202,
)
async def regenerate_segment_endpoint(segment_id: str) -> GenerationTriggerOut:
    """Force regeneration: wipes raw + approved files and ``approved_at``
    synchronously, then enqueues a new job. This is destructive — if the user
    wants to preserve the old approved cut, they should copy it out first.
    """
    _, chapter_id = _segment_context(segment_id)
    try:
        result = await generation.trigger_segment(segment_id, force=True)
    except generation.GenerationError as e:
        raise HTTPException(400, str(e)) from e
    from backend.audio import assembly  # noqa: WPS433 — intentional late import
    assembly.invalidate_chapter_cache(chapter_id)
    return GenerationTriggerOut(
        job_id=result.job_id, estimated_seconds=result.estimated_seconds
    )


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


@router.post("/segments/{segment_id}/approve", response_model=SegmentOut)
def approve_segment(segment_id: str) -> SegmentOut:
    """Copy the segment's raw audio into the approved/ tree and stamp
    ``approved_at``. 409 if no raw audio exists yet — spec §10.5 requires
    the user to generate before approving.
    """
    project_id, chapter_id = _segment_context(segment_id)
    raw_path = _resolve_existing_audio(
        audio_paths.raw_segment_glob, project_id, chapter_id, segment_id
    )
    if raw_path is None:
        raise HTTPException(409, "No audio generated yet for this segment.")

    ext = raw_path.suffix.lstrip(".")
    approved_path = audio_paths.approved_segment_path(
        project_id, chapter_id, segment_id, ext
    )
    # shutil.copy2 preserves mtime — useful when users sort by "newest
    # approved". Overwrites any existing approved file.
    try:
        shutil.copy2(raw_path, approved_path)
    except OSError as e:
        log.exception("approve_segment: copy failed")
        raise HTTPException(500, f"failed to copy raw → approved: {e!s}") from e

    approved_iso = _utcnow_iso_z()
    with connect() as conn:
        conn.execute(
            "UPDATE segments SET status='approved', approved_at=?, "
            "updated_at=datetime('now') WHERE id=?",
            (approved_iso, segment_id),
        )
    # Approval mutates segments.updated_at / approved_at, which feeds the
    # assembly cache hash. Invalidate so the next player request re-assembles.
    from backend.audio import assembly  # noqa: WPS433 — intentional late import
    assembly.invalidate_chapter_cache(chapter_id)
    return _segment_out(segment_id)


@router.post("/segments/{segment_id}/reject", response_model=SegmentOut)
def reject_segment(segment_id: str) -> SegmentOut:
    """Clear ``approved_at`` so the segment re-enters the review queue.

    Status is *not* touched — if the segment was ``approved`` we drop it back
    to ``generated``; otherwise we leave whatever the current status is
    alone (so rejecting a segment that's already ``generated`` is a no-op
    on status and just guarantees ``approved_at`` is NULL).
    Files are not deleted — the user may want to re-approve later.
    """
    _, chapter_id = _segment_context(segment_id)
    with connect() as conn:
        conn.execute(
            """
            UPDATE segments
            SET approved_at = NULL,
                status = CASE WHEN status = 'approved' THEN 'generated' ELSE status END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (segment_id,),
        )
    from backend.audio import assembly  # noqa: WPS433 — intentional late import
    assembly.invalidate_chapter_cache(chapter_id)
    return _segment_out(segment_id)


# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------


@router.get("/segments/{segment_id}/audio")
def get_segment_audio(segment_id: str) -> FileResponse:
    """Stream the raw generated audio file. 404 if nothing has been
    generated yet."""
    project_id, chapter_id = _segment_context(segment_id)
    path = _resolve_existing_audio(
        audio_paths.raw_segment_glob, project_id, chapter_id, segment_id
    )
    if path is None:
        raise HTTPException(404, "no raw audio for segment")
    return FileResponse(
        path,
        media_type=audio_paths.content_type_from_ext(path.suffix),
        filename=path.name,
    )


@router.get("/segments/{segment_id}/audio/approved")
def get_segment_audio_approved(segment_id: str) -> FileResponse:
    """Stream the approved audio file. 404 if not yet approved."""
    project_id, chapter_id = _segment_context(segment_id)
    path = _resolve_existing_audio(
        audio_paths.approved_segment_glob, project_id, chapter_id, segment_id
    )
    if path is None:
        raise HTTPException(404, "no approved audio for segment")
    return FileResponse(
        path,
        media_type=audio_paths.content_type_from_ext(path.suffix),
        filename=path.name,
    )


# ---------------------------------------------------------------------------
# Chapter-level endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/chapters/{chapter_id}/generate",
    response_model=ChapterGenerationTriggerOut,
    status_code=202,
)
async def generate_chapter_endpoint(chapter_id: str) -> ChapterGenerationTriggerOut:
    """Enqueue ``generate_segment`` jobs for every ungenerated segment in
    the chapter. Returns one job id per segment enqueued."""
    try:
        result = await generation.trigger_chapter(
            chapter_id, include_already_generated=False
        )
    except generation.GenerationError as e:
        raise HTTPException(404, str(e)) from e
    return ChapterGenerationTriggerOut(
        job_ids=result.job_ids,
        segment_count=result.segment_count,
        total_estimated_seconds=result.total_estimated_seconds,
    )


@router.get(
    "/chapters/{chapter_id}/generation-estimate",
    response_model=GenerationEstimateOut,
)
def chapter_generation_estimate(chapter_id: str) -> GenerationEstimateOut:
    """Duration estimate for segments that still need to be generated."""
    # Validate chapter exists (helper raises if missing).
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"chapter {chapter_id!r} not found")
        est = generation.estimate_chapter_ungenerated(chapter_id, conn=conn)
    return GenerationEstimateOut(
        seconds=est.seconds,
        words=est.words,
        segments=est.segments,
        wps_factor=est.wps_factor,
        human_label=est.human_label,
    )


@router.get(
    "/chapters/{chapter_id}/generation-status",
    response_model=ChapterGenerationStatusOut,
)
def chapter_generation_status(chapter_id: str) -> ChapterGenerationStatusOut:
    """Aggregate status counts + in-flight job ids for this chapter's
    ``generate_segment`` jobs.

    Jobs are cross-referenced by segment_id embedded in the payload JSON —
    there's no chapter_id on the jobs row today, but every segment_id in a
    chapter is known so we can filter precisely.
    """
    with connect() as conn:
        chapter = conn.execute(
            "SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
        if not chapter:
            raise HTTPException(404, f"chapter {chapter_id!r} not found")

        counts: dict[str, int] = {
            "pending": 0,
            "generating": 0,
            "generated": 0,
            "approved": 0,
            "error": 0,
        }
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM segments WHERE chapter_id = ? GROUP BY status",
            (chapter_id,),
        ).fetchall()
        total = 0
        for r in rows:
            status = r["status"]
            n = r["n"] or 0
            total += n
            if status in counts:
                counts[status] = n
            else:
                # Unexpected value — schema CHECK should prevent this.
                log.warning(
                    "chapter %s has segment with unknown status %r",
                    chapter_id, status,
                )

        segment_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM segments WHERE chapter_id = ?", (chapter_id,)
            ).fetchall()
        }

        in_progress: list[str] = []
        if segment_ids:
            # Filter by kind + status in SQL; match segment_id in Python because
            # the payload is opaque JSON. A JSON1-backed query would be tighter
            # but for typical chapter sizes (<~500 segments) this is trivial.
            import json as _json
            job_rows = conn.execute(
                """
                SELECT id, payload_json FROM jobs
                WHERE kind = 'generate_segment'
                  AND status IN ('queued', 'running', 'awaiting_response')
                """
            ).fetchall()
            for jr in job_rows:
                try:
                    pl = _json.loads(jr["payload_json"] or "{}")
                except (TypeError, ValueError):
                    continue
                if pl.get("segment_id") in segment_ids:
                    in_progress.append(jr["id"])

    return ChapterGenerationStatusOut(
        total=total,
        pending=counts["pending"],
        generating=counts["generating"],
        generated=counts["generated"],
        approved=counts["approved"],
        error=counts["error"],
        in_progress_job_ids=in_progress,
    )
