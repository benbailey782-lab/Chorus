"""Chapter attribution + segment editing API (§16)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from backend.db import connect
from backend.nlp import attribute_chapter
from backend.schemas import (
    AttributeAllResponse,
    AttributeResponse,
    BulkReassignRequest,
    BulkReassignResponse,
    SegmentCharacter,
    SegmentOut,
    SegmentUpdate,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["segments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_segment(row, character_row: Optional[Any]) -> SegmentOut:
    d = dict(row)
    try:
        tags = json.loads(d.get("emotion_tags_json") or "[]")
    except json.JSONDecodeError:
        tags = []
    character: Optional[SegmentCharacter] = None
    if character_row is not None:
        character = SegmentCharacter(
            id=character_row["id"],
            name=character_row["name"],
            character_archetype=character_row["character_archetype"],
            voice_id=character_row["voice_id"],
        )
    return SegmentOut(
        id=d["id"],
        chapter_id=d["chapter_id"],
        order_index=d["order_index"],
        text=d["text"],
        render_mode=d["render_mode"],
        emotion_tags=tags if isinstance(tags, list) else [],
        confidence=d.get("confidence"),
        notes=d.get("notes"),
        character=character,
        voice_override_id=d.get("voice_override_id"),
        audio_path=d.get("audio_path"),
        duration_ms=d.get("duration_ms"),
        status=d.get("status", "pending"),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


def _resolve_project_id(id_or_slug: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (id_or_slug, id_or_slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"project {id_or_slug!r} not found")
    return row["id"]


def _chapter_project_id(chapter_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"chapter {chapter_id!r} not found")
    return row["project_id"]


def _segment_project_id(segment_id: str) -> tuple[str, str]:
    """Return (project_id, chapter_id) for a segment, 404 if missing."""
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


def _character_in_project(character_id: str, project_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM characters WHERE id=? AND project_id=?",
            (character_id, project_id),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Trigger routes
# ---------------------------------------------------------------------------


@router.post(
    "/chapters/{chapter_id}/attribute",
    response_model=AttributeResponse,
    status_code=202,
)
async def attribute_one_chapter(chapter_id: str) -> AttributeResponse:
    try:
        result = await attribute_chapter.trigger(chapter_id)
    except attribute_chapter.AttributeChapterError as e:
        raise HTTPException(400, str(e)) from e
    return AttributeResponse(
        job_id=result.job_id,
        request_path=result.request_path,
        chapter_chars=result.chapter_chars,
        cast_size=result.cast_size,
    )


@router.post(
    "/projects/{id_or_slug}/attribute-all",
    response_model=AttributeAllResponse,
    status_code=202,
)
async def attribute_all_chapters(id_or_slug: str) -> AttributeAllResponse:
    project_id = _resolve_project_id(id_or_slug)
    with connect() as conn:
        chapter_rows = conn.execute(
            """
            SELECT c.id AS id,
                   EXISTS(SELECT 1 FROM segments s WHERE s.chapter_id = c.id) AS has_segments
            FROM chapters c
            WHERE c.project_id = ?
            ORDER BY c.number
            """,
            (project_id,),
        ).fetchall()

    to_attribute = [r["id"] for r in chapter_rows if not r["has_segments"]]
    skipped = [r["id"] for r in chapter_rows if r["has_segments"]]

    job_ids: list[str] = []
    for ch_id in to_attribute:
        try:
            result = await attribute_chapter.trigger(ch_id)
            job_ids.append(result.job_id)
        except attribute_chapter.AttributeChapterError as e:
            log.warning("attribute-all: skipping chapter %s — %s", ch_id, e)
    return AttributeAllResponse(
        chapter_count=len(job_ids),
        job_ids=job_ids,
        skipped_chapter_ids=skipped,
    )


# ---------------------------------------------------------------------------
# Segment CRUD
# ---------------------------------------------------------------------------


def _load_segments_with_characters(chapter_id: str) -> list[SegmentOut]:
    with connect() as conn:
        seg_rows = conn.execute(
            "SELECT * FROM segments WHERE chapter_id=? ORDER BY order_index",
            (chapter_id,),
        ).fetchall()
        char_ids = {r["character_id"] for r in seg_rows if r["character_id"]}
        char_rows = {}
        if char_ids:
            placeholders = ",".join("?" * len(char_ids))
            rows = conn.execute(
                f"SELECT id, name, character_archetype, voice_id "
                f"FROM characters WHERE id IN ({placeholders})",
                list(char_ids),
            ).fetchall()
            char_rows = {r["id"]: r for r in rows}
    return [
        _row_to_segment(s, char_rows.get(s["character_id"]) if s["character_id"] else None)
        for s in seg_rows
    ]


@router.get(
    "/chapters/{chapter_id}/segments",
    response_model=list[SegmentOut],
)
def list_segments(chapter_id: str) -> list[SegmentOut]:
    _chapter_project_id(chapter_id)  # 404 if chapter missing
    return _load_segments_with_characters(chapter_id)


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def update_segment(segment_id: str, body: SegmentUpdate) -> SegmentOut:
    project_id, _ = _segment_project_id(segment_id)
    patch = body.model_dump(exclude_unset=True)

    if "character_id" in patch and patch["character_id"] is not None:
        if not _character_in_project(patch["character_id"], project_id):
            raise HTTPException(
                400,
                f"character_id {patch['character_id']!r} is not in this project's cast",
            )

    sets: list[str] = []
    params: list[Any] = []
    for col in ("character_id", "render_mode", "text", "notes"):
        if col in patch:
            sets.append(f"{col} = ?")
            params.append(patch[col])
    if "emotion_tags" in patch:
        sets.append("emotion_tags_json = ?")
        params.append(json.dumps(patch["emotion_tags"] or [], ensure_ascii=False))

    if not sets:
        return _segment_to_out(segment_id)

    sets.append("updated_at = datetime('now')")
    params.append(segment_id)
    with connect() as conn:
        conn.execute(f"UPDATE segments SET {', '.join(sets)} WHERE id = ?", params)
    return _segment_to_out(segment_id)


def _segment_to_out(segment_id: str) -> SegmentOut:
    with connect() as conn:
        seg = conn.execute(
            "SELECT * FROM segments WHERE id=?", (segment_id,)
        ).fetchone()
        if not seg:
            raise HTTPException(404, f"segment {segment_id!r} not found")
        char = None
        if seg["character_id"]:
            char = conn.execute(
                "SELECT id, name, character_archetype, voice_id "
                "FROM characters WHERE id=?",
                (seg["character_id"],),
            ).fetchone()
    return _row_to_segment(seg, char)


@router.post("/segments/bulk-reassign", response_model=BulkReassignResponse)
def bulk_reassign(body: BulkReassignRequest) -> BulkReassignResponse:
    if not body.segment_ids:
        return BulkReassignResponse(updated=0)

    changes = body.changes
    # Load all segments + project_ids up front for validation.
    with connect() as conn:
        placeholders = ",".join("?" * len(body.segment_ids))
        rows = conn.execute(
            f"""
            SELECT s.id AS id, s.chapter_id AS chapter_id, s.emotion_tags_json AS tags,
                   c.project_id AS project_id
            FROM segments s JOIN chapters c ON s.chapter_id = c.id
            WHERE s.id IN ({placeholders})
            """,
            body.segment_ids,
        ).fetchall()
    if len(rows) != len(body.segment_ids):
        missing = set(body.segment_ids) - {r["id"] for r in rows}
        raise HTTPException(404, f"segments not found: {sorted(missing)}")

    project_ids = {r["project_id"] for r in rows}
    if len(project_ids) > 1:
        raise HTTPException(400, "bulk-reassign targets segments across multiple projects")
    project_id = next(iter(project_ids))

    if changes.character_id is not None and not _character_in_project(
        changes.character_id, project_id
    ):
        raise HTTPException(
            400,
            f"character_id {changes.character_id!r} is not in this project's cast",
        )

    updated = 0
    with connect() as conn:
        for r in rows:
            sets: list[str] = []
            params: list[Any] = []
            if changes.character_id is not None:
                sets.append("character_id = ?")
                params.append(changes.character_id)
            if changes.render_mode is not None:
                sets.append("render_mode = ?")
                params.append(changes.render_mode)
            if changes.add_emotion_tags or changes.remove_emotion_tags:
                try:
                    tags = json.loads(r["tags"] or "[]")
                    if not isinstance(tags, list):
                        tags = []
                except json.JSONDecodeError:
                    tags = []
                tags_lower = {str(t).lower() for t in tags}
                for t in changes.add_emotion_tags or []:
                    if t.lower() not in tags_lower:
                        tags.append(t)
                        tags_lower.add(t.lower())
                if changes.remove_emotion_tags:
                    remove_lower = {t.lower() for t in changes.remove_emotion_tags}
                    tags = [t for t in tags if t.lower() not in remove_lower]
                sets.append("emotion_tags_json = ?")
                params.append(json.dumps(tags, ensure_ascii=False))
            if not sets:
                continue
            sets.append("updated_at = datetime('now')")
            params.append(r["id"])
            conn.execute(
                f"UPDATE segments SET {', '.join(sets)} WHERE id = ?", params
            )
            updated += 1
    return BulkReassignResponse(updated=updated)


@router.get("/segments/{segment_id}/preview")
def segment_preview(segment_id: str) -> Any:
    """501 stub — Voicebox needed (Phase 5)."""
    raise HTTPException(
        501,
        "Segment audio preview requires Voicebox (Phase 5). "
        "For now, read the text in the review UI or inspect the segment row directly.",
    )
