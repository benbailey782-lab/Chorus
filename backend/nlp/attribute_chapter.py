"""Pass 4 — Chapter Attribution (§10.4) via file-drop (§12A).

Pattern-matches ``extract_characters.py`` and ``auto_cast.py``: ``trigger``
async-kicks a file-drop request, ``handle_response`` validates and ingests
the companion-session's JSON reply.

Per Phase 4 instructions: validates every ``character`` name in the payload
against the project's cast (not the voice library), replaces any existing
segments for the chapter (re-run == replace), recomputes
``characters.line_count`` across the whole project, and advances project
status through ``casting`` → ``attributing`` → ``attributed``.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from backend.db import connect
from backend.jobs import repo, worker
from backend.nlp import file_drop, render

log = logging.getLogger(__name__)

JOB_KIND = "attribute_chapter"
PROMPT_NAME = "attribute_chapter.md"

REQUIRED_FIELDS = ("order", "character", "text", "render_mode", "confidence")

VALID_RENDER_MODES = {
    "prose", "dialogue", "epigraph", "letter", "poetry",
    "song_lyrics", "emphasis", "thought", "chapter_heading",
}


class AttributeChapterError(RuntimeError):
    """Raised when chapter attribution can't be triggered or ingested."""


@dataclass
class AttributeChapterTriggerResult:
    job_id: str
    request_path: str
    chapter_chars: int
    cast_size: int


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def _build_cast_json(project_id: str) -> list[dict[str, Any]]:
    """Cast shape the attribute_chapter.md prompt expects."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, aliases_json, gender, age_estimate, description,
                   speaking_style, character_archetype, is_narrator
            FROM characters WHERE project_id=? ORDER BY id
            """,
            (project_id,),
        ).fetchall()
    cast: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            aliases = json.loads(d.pop("aliases_json") or "[]")
        except json.JSONDecodeError:
            aliases = []
        d["aliases"] = aliases if isinstance(aliases, list) else []
        d["is_narrator"] = bool(d.get("is_narrator"))
        cast.append(d)
    return cast


def _pov_character_name(pov_character_id: Optional[str]) -> str:
    if not pov_character_id:
        return ""
    with connect() as conn:
        row = conn.execute(
            "SELECT name FROM characters WHERE id=?", (pov_character_id,)
        ).fetchone()
    return row["name"] if row else ""


async def trigger(chapter_id: str) -> AttributeChapterTriggerResult:
    with connect() as conn:
        chapter = conn.execute(
            "SELECT * FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not chapter:
        raise AttributeChapterError(f"chapter {chapter_id!r} not found")
    project_id = chapter["project_id"]

    cast = _build_cast_json(project_id)
    if not cast:
        raise AttributeChapterError(
            "project has no cast yet — run extract-cast before attributing chapters"
        )

    prompt_text = render.load_prompt(
        PROMPT_NAME,
        {
            "CAST_JSON": json.dumps(cast, ensure_ascii=False, indent=2),
            "CHAPTER_NUMBER": str(chapter["number"]),
            "CHAPTER_TITLE": chapter["title"] or "",
            "CHAPTER_TEXT": chapter["raw_text"],
            "POV_CHARACTER_NAME": _pov_character_name(chapter["pov_character_id"]),
        },
    )

    job = repo.create_job(
        project_id=project_id,
        kind=JOB_KIND,
        payload={
            "chapter_id": chapter_id,
            "chapter_number": chapter["number"],
            "chapter_chars": len(chapter["raw_text"]),
            "cast_size": len(cast),
        },
        status="awaiting_response",
        message="Awaiting companion Claude Code response (see data/llm_queue/pending/)",
    )

    # Bump project status to "attributing" when the first attribute job lands,
    # but only if the project is still in "casting" — don't overwrite
    # "attributed" or any later status.
    with connect() as conn:
        conn.execute(
            "UPDATE projects SET status='attributing', updated_at=datetime('now') "
            "WHERE id=? AND status='casting'",
            (project_id,),
        )

    path = await file_drop.submit_request(
        job["id"],
        prompt_text,
        metadata={
            "kind": JOB_KIND,
            "project_id": project_id,
            "chapter_id": chapter_id,
            "chapter_number": chapter["number"],
            "chapter_title": chapter["title"] or "",
            "chapter_chars": len(chapter["raw_text"]),
        },
    )
    log.info(
        "attribute-chapter job %s queued (chapter=%s #%s, %d chars)",
        job["id"], chapter_id, chapter["number"], len(chapter["raw_text"]),
    )
    return AttributeChapterTriggerResult(
        job_id=job["id"],
        request_path=str(path),
        chapter_chars=len(chapter["raw_text"]),
        cast_size=len(cast),
    )


# ---------------------------------------------------------------------------
# Response ingestion
# ---------------------------------------------------------------------------


def _validate_segments(
    payload: Any, name_to_id: dict[str, str]
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return [], [f"expected a JSON array, got {type(payload).__name__}"]
    if not payload:
        return [], ["response contained zero segments"]
    valid: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    # case-insensitive name resolution — the prompt's few-shots use canonical
    # capitalization but LLM output can drift ("narrator" vs "Narrator").
    name_to_id_lower = {k.lower(): v for k, v in name_to_id.items()}
    for i, entry in enumerate(payload):
        if not isinstance(entry, dict):
            errors.append(f"segment #{i}: not a JSON object")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in entry or entry.get(f) is None]
        if missing:
            errors.append(f"segment #{i}: missing {missing}")
            continue
        try:
            order = int(entry["order"])
        except (TypeError, ValueError):
            errors.append(f"segment #{i}: invalid order {entry.get('order')!r}")
            continue
        if order in seen_orders:
            errors.append(f"segment #{i}: duplicate order {order}")
            continue
        seen_orders.add(order)
        render_mode = str(entry["render_mode"])
        if render_mode not in VALID_RENDER_MODES:
            errors.append(
                f"segment #{i} (order {order}): invalid render_mode {render_mode!r}"
            )
            continue
        name = str(entry["character"]).strip()
        if name.lower() not in name_to_id_lower:
            errors.append(
                f"segment #{i} (order {order}): unknown character {name!r} "
                "(not in project cast)"
            )
            continue
        try:
            conf = int(entry["confidence"])
        except (TypeError, ValueError):
            conf = 0
        conf = max(0, min(100, conf))
        tags = entry.get("emotion_tags") or []
        if not isinstance(tags, list):
            tags = []
        valid.append({
            "order": order,
            "character_id": name_to_id_lower[name.lower()],
            "text": str(entry["text"]),
            "render_mode": render_mode,
            "emotion_tags": [str(t) for t in tags],
            "confidence": conf,
            "notes": entry.get("notes") if entry.get("notes") else None,
        })
    return valid, errors


def _recompute_line_counts(project_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE characters
            SET line_count = COALESCE((
                SELECT COUNT(*) FROM segments s
                JOIN chapters c ON s.chapter_id = c.id
                WHERE s.character_id = characters.id
                  AND c.project_id = characters.project_id
                  AND s.render_mode = 'dialogue'
            ), 0)
            WHERE project_id = ?
            """,
            (project_id,),
        )


def _advance_project_status(project_id: str) -> str:
    """Transition project.status per Phase 4 rules. Returns the new status."""
    with connect() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN EXISTS(
                        SELECT 1 FROM segments s WHERE s.chapter_id = chapters.id
                   ) THEN 1 ELSE 0 END) AS attributed
            FROM chapters WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        total = totals["total"] or 0
        attributed = totals["attributed"] or 0
        if total > 0 and attributed == total:
            new_status = "attributed"
        else:
            new_status = "attributing"
        conn.execute(
            "UPDATE projects SET status=?, updated_at=datetime('now') WHERE id=?",
            (new_status, project_id),
        )
    return new_status


@worker.register_handler(JOB_KIND)
async def handle_response(job: dict[str, Any], payload: Any) -> None:
    project_id: Optional[str] = job.get("project_id")
    if not project_id:
        raise AttributeChapterError("job has no project_id")
    chapter_id = (job.get("payload") or {}).get("chapter_id")
    if not chapter_id:
        raise AttributeChapterError("job payload is missing chapter_id")

    # Build the name → id map for this project's cast.
    with connect() as conn:
        name_to_id = {
            r["name"]: r["id"]
            for r in conn.execute(
                "SELECT id, name FROM characters WHERE project_id=?", (project_id,)
            ).fetchall()
        }
    if not name_to_id:
        raise AttributeChapterError(
            "project has no cast — extract-cast must run before attribution"
        )

    valid, errors = _validate_segments(payload, name_to_id)
    if errors:
        joined = "; ".join(errors[:8])
        more = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
        raise AttributeChapterError(f"attribution response failed validation: {joined}{more}")

    with connect() as conn:
        # Replace any existing segments for this chapter (re-run == replace).
        conn.execute("DELETE FROM segments WHERE chapter_id=?", (chapter_id,))
        for seg in valid:
            conn.execute(
                """
                INSERT INTO segments (
                    id, chapter_id, character_id, order_index, text, render_mode,
                    emotion_tags_json, confidence, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    chapter_id,
                    seg["character_id"],
                    seg["order"],
                    seg["text"],
                    seg["render_mode"],
                    json.dumps(seg["emotion_tags"], ensure_ascii=False),
                    seg["confidence"],
                    seg["notes"],
                ),
            )
        conn.execute(
            "UPDATE chapters SET status='attributed' WHERE id=?", (chapter_id,)
        )

    _recompute_line_counts(project_id)
    new_status = _advance_project_status(project_id)

    repo.set_status(
        job["id"],
        "complete",
        result={
            "inserted": len(valid),
            "chapter_id": chapter_id,
            "project_status": new_status,
        },
        message=f"Inserted {len(valid)} segments; project status → {new_status}",
    )
    log.info(
        "attribute-chapter job %s complete — %d segments; project status=%s",
        job["id"], len(valid), new_status,
    )
