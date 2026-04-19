"""Pronunciations API (§9.6 + §10.3).

Global and project-scoped CRUD, promotion from project → global, Pass-3
extraction trigger, and a merged read view that the generation pipeline will
use when doing text substitution.

Route shape rationale: global entries live under ``/api/pronunciations/global``
and project entries under ``/api/projects/{...}/pronunciations``. PATCH and
DELETE on an individual id have two variants so the endpoint unambiguously
tells the handler whether the id refers to a global or a project row — both
tables use UUIDs so IDs could in principle collide, and guessing based on a
lookup would silently do the wrong thing on a collision.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from backend.db import connect
from backend.nlp import merge_pronunciations as merge_mod
from backend.nlp import pronounce_unusual_handler
from backend.schemas import (
    MergedPronunciationOut,
    PromoteToGlobalRequest,
    PronunciationCreate,
    PronunciationExtractResponse,
    PronunciationOut,
    PronunciationUpdate,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pronunciations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_project_id(id_or_slug: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (id_or_slug, id_or_slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"project {id_or_slug!r} not found")
    return row["id"]


def _row_to_out(row, *, project_id: Optional[str]) -> PronunciationOut:
    return PronunciationOut(
        id=row["id"],
        project_id=project_id,
        term=row["term"],
        phonetic=row["phonetic"],
        ipa=row["ipa"],
        confidence=row["confidence"],
        category=row["category"],
        notes=row["notes"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_term_phonetic(term: str, phonetic: str) -> None:
    if not term or not term.strip():
        raise HTTPException(422, "term is required and cannot be empty")
    if not phonetic or not phonetic.strip():
        raise HTTPException(422, "phonetic is required and cannot be empty")


# ---------------------------------------------------------------------------
# Global scope
# ---------------------------------------------------------------------------


@router.get("/pronunciations/global", response_model=list[PronunciationOut])
def list_global_pronunciations() -> list[PronunciationOut]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pronunciations_global ORDER BY term COLLATE NOCASE"
        ).fetchall()
    return [_row_to_out(r, project_id=None) for r in rows]


@router.post(
    "/pronunciations/global",
    response_model=PronunciationOut,
    status_code=201,
)
def create_global_pronunciation(body: PronunciationCreate) -> PronunciationOut:
    _validate_term_phonetic(body.term, body.phonetic)
    term = body.term.strip()
    phonetic = body.phonetic.strip()
    new_id = str(uuid.uuid4())
    with connect() as conn:
        dup = conn.execute(
            "SELECT 1 FROM pronunciations_global WHERE term=? COLLATE NOCASE",
            (term,),
        ).fetchone()
        if dup:
            raise HTTPException(
                409, f"a global pronunciation for {term!r} already exists"
            )
        conn.execute(
            """
            INSERT INTO pronunciations_global (
                id, term, phonetic, ipa, confidence, category, notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id, term, phonetic, body.ipa, body.confidence,
                body.category, body.notes, body.source,
            ),
        )
        row = conn.execute(
            "SELECT * FROM pronunciations_global WHERE id=?", (new_id,)
        ).fetchone()
    return _row_to_out(row, project_id=None)


@router.patch(
    "/pronunciations/global/{pron_id}", response_model=PronunciationOut
)
def update_global_pronunciation(
    pron_id: str, body: PronunciationUpdate
) -> PronunciationOut:
    patch = body.model_dump(exclude_unset=True)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pronunciations_global WHERE id=?", (pron_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"global pronunciation {pron_id!r} not found")
        if not patch:
            return _row_to_out(row, project_id=None)
        # Sanity: if term changes, ensure no other global row already holds it.
        if "term" in patch:
            new_term = (patch["term"] or "").strip()
            if not new_term:
                raise HTTPException(422, "term cannot be empty")
            patch["term"] = new_term
            dup = conn.execute(
                "SELECT 1 FROM pronunciations_global WHERE term=? COLLATE NOCASE AND id<>?",
                (new_term, pron_id),
            ).fetchone()
            if dup:
                raise HTTPException(
                    409, f"another global pronunciation for {new_term!r} already exists"
                )
        if "phonetic" in patch:
            pv = (patch["phonetic"] or "").strip()
            if not pv:
                raise HTTPException(422, "phonetic cannot be empty")
            patch["phonetic"] = pv
        sets = [f"{k} = ?" for k in patch.keys()] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(patch.values()) + [pron_id]
        conn.execute(
            f"UPDATE pronunciations_global SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        row = conn.execute(
            "SELECT * FROM pronunciations_global WHERE id=?", (pron_id,)
        ).fetchone()
    return _row_to_out(row, project_id=None)


@router.delete("/pronunciations/global/{pron_id}", status_code=204)
def delete_global_pronunciation(pron_id: str) -> Response:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM pronunciations_global WHERE id=?", (pron_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"global pronunciation {pron_id!r} not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Project scope
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{id_or_slug}/pronunciations",
    response_model=list[PronunciationOut],
)
def list_project_pronunciations(id_or_slug: str) -> list[PronunciationOut]:
    project_id = _resolve_project_id(id_or_slug)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pronunciations WHERE project_id=? "
            "ORDER BY term COLLATE NOCASE",
            (project_id,),
        ).fetchall()
    return [_row_to_out(r, project_id=project_id) for r in rows]


@router.post(
    "/projects/{id_or_slug}/pronunciations",
    response_model=PronunciationOut,
    status_code=201,
)
def create_project_pronunciation(
    id_or_slug: str, body: PronunciationCreate
) -> PronunciationOut:
    _validate_term_phonetic(body.term, body.phonetic)
    project_id = _resolve_project_id(id_or_slug)
    term = body.term.strip()
    phonetic = body.phonetic.strip()
    new_id = str(uuid.uuid4())
    with connect() as conn:
        dup = conn.execute(
            "SELECT 1 FROM pronunciations WHERE project_id=? AND term=? COLLATE NOCASE",
            (project_id, term),
        ).fetchone()
        if dup:
            raise HTTPException(
                409,
                f"a project pronunciation for {term!r} already exists in this project",
            )
        conn.execute(
            """
            INSERT INTO pronunciations (
                id, project_id, term, phonetic, ipa, confidence, category, notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id, project_id, term, phonetic, body.ipa, body.confidence,
                body.category, body.notes, body.source,
            ),
        )
        row = conn.execute(
            "SELECT * FROM pronunciations WHERE id=?", (new_id,)
        ).fetchone()
    return _row_to_out(row, project_id=project_id)


@router.patch("/pronunciations/{pron_id}", response_model=PronunciationOut)
def update_project_pronunciation(
    pron_id: str, body: PronunciationUpdate
) -> PronunciationOut:
    """PATCH a project-scoped entry. Global entries use /pronunciations/global/{id}."""
    patch = body.model_dump(exclude_unset=True)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pronunciations WHERE id=?", (pron_id,)
        ).fetchone()
        if not row:
            raise HTTPException(
                404,
                f"project pronunciation {pron_id!r} not found "
                "(for global entries use PATCH /api/pronunciations/global/{id})",
            )
        if not patch:
            return _row_to_out(row, project_id=row["project_id"])
        if "term" in patch:
            new_term = (patch["term"] or "").strip()
            if not new_term:
                raise HTTPException(422, "term cannot be empty")
            patch["term"] = new_term
            dup = conn.execute(
                "SELECT 1 FROM pronunciations WHERE project_id=? AND term=? "
                "COLLATE NOCASE AND id<>?",
                (row["project_id"], new_term, pron_id),
            ).fetchone()
            if dup:
                raise HTTPException(
                    409, f"another pronunciation for {new_term!r} already exists in this project"
                )
        if "phonetic" in patch:
            pv = (patch["phonetic"] or "").strip()
            if not pv:
                raise HTTPException(422, "phonetic cannot be empty")
            patch["phonetic"] = pv
        sets = [f"{k} = ?" for k in patch.keys()] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(patch.values()) + [pron_id]
        conn.execute(
            f"UPDATE pronunciations SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        row = conn.execute(
            "SELECT * FROM pronunciations WHERE id=?", (pron_id,)
        ).fetchone()
    return _row_to_out(row, project_id=row["project_id"])


@router.delete("/pronunciations/{pron_id}", status_code=204)
def delete_project_pronunciation(pron_id: str) -> Response:
    with connect() as conn:
        cur = conn.execute("DELETE FROM pronunciations WHERE id=?", (pron_id,))
        if cur.rowcount == 0:
            raise HTTPException(
                404,
                f"project pronunciation {pron_id!r} not found "
                "(for global entries use DELETE /api/pronunciations/global/{id})",
            )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Promote project → global
# ---------------------------------------------------------------------------


@router.post(
    "/pronunciations/{pron_id}/promote-to-global",
    response_model=PronunciationOut,
)
def promote_to_global(
    pron_id: str, body: PromoteToGlobalRequest | None = None
) -> PronunciationOut:
    """Copy a project-scoped pronunciation into the global library.

    Default behavior deletes the project row after promotion (the merged view
    already surfaces the global entry). Pass ``delete_project_entry: false`` to
    keep both — useful when a project needs a different phonetic than the
    global one and you want the project override to shadow it.
    """
    opts = body or PromoteToGlobalRequest()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pronunciations WHERE id=?", (pron_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"project pronunciation {pron_id!r} not found")
        existing_global = conn.execute(
            "SELECT id FROM pronunciations_global WHERE term=? COLLATE NOCASE",
            (row["term"],),
        ).fetchone()
        if existing_global:
            # Update the existing global entry with the project row's content.
            global_id = existing_global["id"]
            conn.execute(
                """
                UPDATE pronunciations_global
                SET phonetic=?, ipa=?, confidence=?, category=?, notes=?, source=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    row["phonetic"], row["ipa"], row["confidence"],
                    row["category"], row["notes"], row["source"] or "promoted",
                    global_id,
                ),
            )
        else:
            global_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO pronunciations_global (
                    id, term, phonetic, ipa, confidence, category, notes, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    global_id, row["term"], row["phonetic"], row["ipa"],
                    row["confidence"], row["category"], row["notes"],
                    row["source"] or "promoted",
                ),
            )
        if opts.delete_project_entry:
            conn.execute("DELETE FROM pronunciations WHERE id=?", (pron_id,))
        promoted = conn.execute(
            "SELECT * FROM pronunciations_global WHERE id=?", (global_id,)
        ).fetchone()
    log.info(
        "promoted pronunciation term=%r project_id=%s → global_id=%s (deleted=%s)",
        row["term"], row["project_id"], global_id, opts.delete_project_entry,
    )
    return _row_to_out(promoted, project_id=None)


# ---------------------------------------------------------------------------
# Pass-3 extraction trigger
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{id_or_slug}/pronunciations/extract",
    response_model=PronunciationExtractResponse,
    status_code=202,
)
async def extract_pronunciations(id_or_slug: str) -> PronunciationExtractResponse:
    project_id = _resolve_project_id(id_or_slug)
    try:
        result = await pronounce_unusual_handler.trigger(project_id)
    except pronounce_unusual_handler.PronounceUnusualError as e:
        raise HTTPException(400, str(e)) from e
    return PronunciationExtractResponse(
        job_id=result.job_id,
        request_path=result.request_path,
        book_text_chars=result.book_text_chars,
        truncated=result.truncated,
        cast_size=result.cast_size,
        warnings=result.warnings,
    )


# ---------------------------------------------------------------------------
# Merged view — what generation will actually read
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{id_or_slug}/pronunciations/merged",
    response_model=list[MergedPronunciationOut],
)
def list_merged_pronunciations(id_or_slug: str) -> list[MergedPronunciationOut]:
    project_id = _resolve_project_id(id_or_slug)
    merged = merge_mod.merge_pronunciations(project_id)
    return [
        MergedPronunciationOut(
            term=e.term,
            phonetic=e.phonetic,
            ipa=e.ipa,
            confidence=e.confidence,
            source=e.source,
            origin_id=e.origin_id,
        )
        for e in sorted(merged.values(), key=lambda x: x.term.lower())
    ]
