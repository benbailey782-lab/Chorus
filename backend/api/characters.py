"""Characters + casting API (§16).

Endpoints:
  * ``POST /api/projects/{id}/extract-cast``   — Pass 1 trigger
  * ``POST /api/projects/{id}/auto-cast``      — Pass 2 trigger
  * ``GET  /api/projects/{id}/characters``     — list
  * ``PATCH /api/characters/{id}``             — manual voice override
  * ``POST /api/characters/{id}/preview``      — 501 until Voicebox wiring lands
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import connect
from backend.nlp import auto_cast, extract_characters
from backend.schemas import (
    AutoCastResponse,
    CharacterOut,
    CharacterUpdate,
    ExtractCastResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["characters"])


def _row_to_character(row) -> CharacterOut:
    d = dict(row)
    try:
        aliases = json.loads(d.get("aliases_json") or "[]")
    except json.JSONDecodeError:
        aliases = []
    return CharacterOut(
        id=d["id"],
        project_id=d["project_id"],
        name=d["name"],
        aliases=aliases if isinstance(aliases, list) else [],
        gender=d.get("gender"),
        age_estimate=d.get("age_estimate"),
        description=d.get("description"),
        speaking_style=d.get("speaking_style"),
        character_archetype=d.get("character_archetype"),
        first_appearance_chapter=d.get("first_appearance_chapter"),
        estimated_line_count=d.get("estimated_line_count"),
        line_count=d.get("line_count"),
        is_narrator=bool(d.get("is_narrator", 0)),
        voice_id=d.get("voice_id"),
        engine_override=d.get("engine_override"),
        notes=d.get("notes"),
    )


def _resolve_project_id(id_or_slug: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (id_or_slug, id_or_slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"project {id_or_slug!r} not found")
    return row["id"]


# ---------------------------------------------------------------------------
# List + manual override
# ---------------------------------------------------------------------------


@router.get("/projects/{id_or_slug}/characters", response_model=list[CharacterOut])
def list_characters(id_or_slug: str) -> list[CharacterOut]:
    project_id = _resolve_project_id(id_or_slug)

    # Order the list by the §7.3 pool tier so the casting UI groups naturally:
    # main characters at the top, then supporting, then minor, then background
    # and anything without a tier. Within a tier, narrator first then by name.
    tier_order = {"main": 0, "supporting": 1, "minor": 2, "background": 3}
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM characters WHERE project_id=?",
            (project_id,),
        ).fetchall()
    ordered = sorted(
        rows,
        key=lambda r: (
            tier_order.get(r["estimated_line_count"] or "", 4),
            0 if r["is_narrator"] else 1,
            (r["name"] or "").lower(),
        ),
    )
    return [_row_to_character(r) for r in ordered]


@router.patch("/characters/{character_id}", response_model=CharacterOut)
def update_character(character_id: str, body: CharacterUpdate) -> CharacterOut:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        # No-op PATCH returns the row unchanged.
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE id=?", (character_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, f"character {character_id!r} not found")
        return _row_to_character(row)

    # Validate voice_id is a real voice (when explicitly set, including null).
    if "voice_id" in patch and patch["voice_id"] is not None:
        with connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM voices WHERE id=?", (patch["voice_id"],)
            ).fetchone()
        if not exists:
            raise HTTPException(
                400,
                f"voice_id {patch['voice_id']!r} is not in the voice library",
            )

    sets = [f"{k} = ?" for k in patch.keys()]
    params = list(patch.values()) + [character_id]
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE characters SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"character {character_id!r} not found")
        row = conn.execute(
            "SELECT * FROM characters WHERE id=?", (character_id,)
        ).fetchone()
    return _row_to_character(row)


# ---------------------------------------------------------------------------
# Extract cast (Pass 1)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{id_or_slug}/extract-cast",
    response_model=ExtractCastResponse,
    status_code=202,
)
async def extract_cast(id_or_slug: str) -> ExtractCastResponse:
    project_id = _resolve_project_id(id_or_slug)
    try:
        result = await extract_characters.trigger(project_id)
    except extract_characters.ExtractCastError as e:
        raise HTTPException(400, str(e)) from e
    return ExtractCastResponse(
        job_id=result.job_id,
        request_path=result.request_path,
        book_text_chars=result.book_text_chars,
        truncated=result.truncated,
        warnings=result.warnings,
    )


# ---------------------------------------------------------------------------
# Auto-cast (Pass 2)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{id_or_slug}/auto-cast",
    response_model=AutoCastResponse,
    status_code=202,
)
async def run_auto_cast(id_or_slug: str) -> AutoCastResponse:
    project_id = _resolve_project_id(id_or_slug)
    try:
        result = await auto_cast.trigger(project_id)
    except auto_cast.AutoCastError as e:
        raise HTTPException(400, str(e)) from e
    return AutoCastResponse(
        job_id=result.job_id,
        request_path=result.request_path,
        cast_size=result.cast_size,
        voice_library_size=result.voice_library_size,
    )


# ---------------------------------------------------------------------------
# Preview — Voicebox-gated
# ---------------------------------------------------------------------------


@router.post("/characters/{character_id}/preview")
def character_preview(character_id: str) -> Any:
    """Stub until Voicebox is wired (Phase 5).

    Returns 501 with a clear note so the UI can show "Preview unavailable"
    without probing voice availability.
    """
    raise HTTPException(
        501,
        "Voice preview requires Voicebox (Phase 5). For Phase 3, inspect the "
        "reference audio via GET /api/voices/{voice_id}/sample if uploaded.",
    )
