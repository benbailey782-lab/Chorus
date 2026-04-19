"""Playback-state HTTP surface (Phase 6, §9.7).

Two endpoints let the player persist its cursor per project so the user
can pick up where they left off on another device:

  * ``GET  /api/projects/{id_or_slug}/playback`` — current row, 404 if none.
  * ``PATCH /api/projects/{id_or_slug}/playback`` — upsert; missing fields
    are left unchanged, ``updated_at`` always bumped.

The table has ``project_id`` as primary key so there's at most one row
per project — the most recently played chapter + position. Phase 7 may
split this into per-chapter bookmarks; keeping it single-row keeps the
sync logic trivial in the player controller.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.db import connect
from backend.schemas import PlaybackStateOut, PlaybackStateUpsert

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["playback"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_project_id(id_or_slug: str) -> str:
    """Look up by id first, then by slug. 404 if neither matches."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = ? OR slug = ?",
            (id_or_slug, id_or_slug),
        ).fetchone()
    if not row:
        raise HTTPException(404, f"project {id_or_slug!r} not found")
    return row["id"]


def _row_to_out(row) -> PlaybackStateOut:
    return PlaybackStateOut(
        project_id=row["project_id"],
        chapter_id=row["chapter_id"],
        current_segment_id=row["current_segment_id"],
        position_ms=int(row["position_ms"] or 0),
        speed=float(row["speed"] or 1.0),
        updated_at=row["updated_at"],
    )


def _fetch_state(project_id: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT project_id, chapter_id, current_segment_id, position_ms, "
            "speed, updated_at FROM playback_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{id_or_slug}/playback", response_model=PlaybackStateOut)
def get_playback(id_or_slug: str) -> PlaybackStateOut:
    """Return the persisted playback cursor for this project.

    Two flavors of 404 — project missing vs. no playback row yet. The
    message distinguishes them for clients that care; most clients can
    simply treat any 404 as "no saved position".
    """
    project_id = _resolve_project_id(id_or_slug)
    row = _fetch_state(project_id)
    if row is None:
        raise HTTPException(404, "no playback state for this project")
    return _row_to_out(row)


@router.patch("/{id_or_slug}/playback", response_model=PlaybackStateOut)
def patch_playback(id_or_slug: str, body: PlaybackStateUpsert) -> PlaybackStateOut:
    """Upsert the playback row.

    Only fields supplied in the body are touched; absent fields keep
    their current value (or pick up the column default on insert).
    ``updated_at`` is always bumped to ``datetime('now')`` so the client
    can reason about freshness without a clock of its own.
    """
    project_id = _resolve_project_id(id_or_slug)
    patch = body.model_dump(exclude_unset=True)

    with connect() as conn:
        existing = conn.execute(
            "SELECT project_id, chapter_id, current_segment_id, position_ms, "
            "speed, updated_at FROM playback_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()

        if existing is None:
            # INSERT — patch values override column defaults where provided.
            chapter_id = patch.get("chapter_id")
            current_segment_id = patch.get("current_segment_id")
            position_ms = int(patch.get("position_ms") or 0)
            speed = float(patch.get("speed") if patch.get("speed") is not None else 1.0)
            conn.execute(
                """
                INSERT INTO playback_state
                    (project_id, chapter_id, current_segment_id,
                     position_ms, speed, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (project_id, chapter_id, current_segment_id, position_ms, speed),
            )
        else:
            # UPDATE — build SET clause from provided fields only.
            sets: list[str] = []
            params: list = []
            for col in ("chapter_id", "current_segment_id", "position_ms", "speed"):
                if col in patch:
                    sets.append(f"{col} = ?")
                    params.append(patch[col])
            sets.append("updated_at = datetime('now')")
            params.append(project_id)
            conn.execute(
                f"UPDATE playback_state SET {', '.join(sets)} WHERE project_id = ?",
                params,
            )

        row = conn.execute(
            "SELECT project_id, chapter_id, current_segment_id, position_ms, "
            "speed, updated_at FROM playback_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()

    if row is None:  # defensive — shouldn't happen
        raise HTTPException(500, "playback state upsert failed")
    return _row_to_out(row)
