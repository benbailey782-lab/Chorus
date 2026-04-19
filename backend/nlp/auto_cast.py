"""Pass 2 — Voice Auto-Casting (§10.2) via file-drop (§12A).

Preconditions:
  * Project has ≥1 extracted character (i.e., extract-cast has completed).
  * Voice library has ≥1 voice.

The response shape is an array of assignments matching ``auto_cast_voices.md``'s
output schema: one entry per character, each naming a ``voice_id`` (or null)
plus confidence, reasoning, alternatives, and flags. We trust the prompt to
produce one entry per character_id; we validate IDs exist and silently skip
nothing — unknown ``voice_id`` fails the whole job with a listing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from backend.db import connect
from backend.jobs import repo, worker
from backend.nlp import file_drop, render

log = logging.getLogger(__name__)

JOB_KIND = "auto_cast"
PROMPT_NAME = "auto_cast_voices.md"

# Narrative style is hardcoded for Phase 3 — a per-project override can land
# in Phase 7 (§18 open decisions). This is the AGoT default and a reasonable
# starting point for most modern fantasy.
# TODO(phase7): make narrative_style configurable per project.
DEFAULT_NARRATIVE_STYLE = "third-person limited with POV shifts"


class AutoCastError(RuntimeError):
    """Raised when auto-casting can't be triggered or ingested."""


@dataclass
class AutoCastTriggerResult:
    job_id: str
    request_path: str
    cast_size: int
    voice_library_size: int


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def _build_cast_json(project_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, aliases_json, gender, age_estimate, description,
                   speaking_style, character_archetype, first_appearance_chapter,
                   estimated_line_count, notes
            FROM characters WHERE project_id=? ORDER BY id
            """,
            (project_id,),
        ).fetchall()
    cast = []
    for r in rows:
        d = dict(r)
        try:
            aliases = json.loads(d.pop("aliases_json") or "[]")
        except json.JSONDecodeError:
            aliases = []
        d["aliases"] = aliases if isinstance(aliases, list) else []
        cast.append(d)
    return cast


def _build_voice_library_json() -> list[dict[str, Any]]:
    from backend.voices import library as voice_library

    return voice_library.list_voices()


async def trigger(project_id: str) -> AutoCastTriggerResult:
    with connect() as conn:
        proj = conn.execute(
            "SELECT * FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
    if not proj:
        raise AutoCastError(f"project {project_id!r} not found")

    cast = _build_cast_json(proj["id"])
    if not cast:
        raise AutoCastError(
            "project has no cast yet — run extract-cast before auto-casting"
        )

    voices = _build_voice_library_json()
    if not voices:
        raise AutoCastError(
            "voice library is empty — add at least one voice before auto-casting"
        )

    prompt_text = render.load_prompt(
        PROMPT_NAME,
        {
            "CAST_JSON": json.dumps(cast, ensure_ascii=False, indent=2),
            "VOICE_LIBRARY_JSON": json.dumps(voices, ensure_ascii=False, indent=2),
            "BOOK_TITLE": proj["title"],
            "BOOK_AUTHOR": proj["author"] or "Unknown",
            "NARRATIVE_STYLE": DEFAULT_NARRATIVE_STYLE,
        },
    )

    job = repo.create_job(
        project_id=proj["id"],
        kind=JOB_KIND,
        payload={"cast_size": len(cast), "voice_library_size": len(voices)},
        status="awaiting_response",
        message="Awaiting companion Claude Code response (see data/llm_queue/pending/)",
    )

    path = await file_drop.submit_request(
        job["id"],
        prompt_text,
        metadata={
            "kind": JOB_KIND,
            "project_slug": proj["slug"],
            "project_id": proj["id"],
            "cast_size": len(cast),
            "voice_library_size": len(voices),
        },
    )
    log.info(
        "auto-cast job %s queued (project=%s, cast=%d, voices=%d)",
        job["id"],
        proj["slug"],
        len(cast),
        len(voices),
    )
    return AutoCastTriggerResult(
        job_id=job["id"],
        request_path=str(path),
        cast_size=len(cast),
        voice_library_size=len(voices),
    )


# ---------------------------------------------------------------------------
# Response ingestion
# ---------------------------------------------------------------------------


def _apply_assignments(
    project_id: str, assignments: list[dict[str, Any]]
) -> dict[str, Any]:
    with connect() as conn:
        char_rows = conn.execute(
            "SELECT id FROM characters WHERE project_id=?", (project_id,)
        ).fetchall()
        project_char_ids = {r["id"] for r in char_rows}

        voice_rows = conn.execute("SELECT id FROM voices").fetchall()
        known_voice_ids = {r["id"] for r in voice_rows}

    assigned = 0
    unassigned = 0
    for a in assignments:
        cid = a.get("character_id")
        if cid not in project_char_ids:
            # Prompt responses sometimes include the narrator or other synthetic
            # entries not in our DB; log and skip.
            continue
        voice_id = a.get("voice_id")
        engine_override = a.get("engine_override")
        with connect() as conn:
            conn.execute(
                """
                UPDATE characters
                SET voice_id = ?, engine_override = ?
                WHERE id = ? AND project_id = ?
                """,
                (voice_id, engine_override, cid, project_id),
            )
        if voice_id:
            assigned += 1
        else:
            unassigned += 1

    return {"assigned": assigned, "unassigned": unassigned, "known_voice_ids": known_voice_ids}


def _validate_assignments(
    payload: Any, project_char_ids: set[str], known_voice_ids: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return [], [f"expected a JSON array, got {type(payload).__name__}"]
    valid: list[dict[str, Any]] = []
    seen_chars: set[str] = set()
    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            errors.append(f"entry #{idx}: not a JSON object")
            continue
        cid = entry.get("character_id")
        if not cid:
            errors.append(f"entry #{idx}: missing character_id")
            continue
        if cid in seen_chars:
            errors.append(f"entry #{idx}: duplicate character_id {cid!r}")
            continue
        seen_chars.add(cid)
        vid = entry.get("voice_id")
        if vid is not None and vid not in known_voice_ids:
            errors.append(
                f"entry #{idx} ({entry.get('character_name', cid)!r}): "
                f"voice_id {vid!r} is not in the voice library"
            )
            continue
        valid.append(entry)
    # character_ids in the payload that aren't in this project aren't fatal —
    # the prompt may include Narrator. We'll silently skip them in _apply.
    return valid, errors


@worker.register_handler(JOB_KIND)
async def handle_response(job: dict[str, Any], payload: Any) -> None:
    project_id: Optional[str] = job.get("project_id")
    if not project_id:
        raise AutoCastError("job has no project_id")

    with connect() as conn:
        char_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM characters WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        known_voice_ids = {r["id"] for r in conn.execute("SELECT id FROM voices").fetchall()}

    valid, errors = _validate_assignments(payload, char_ids, known_voice_ids)
    if errors:
        joined = "; ".join(errors[:6])
        more = f" (+{len(errors) - 6} more)" if len(errors) > 6 else ""
        raise AutoCastError(f"auto-cast response failed validation: {joined}{more}")
    if not valid:
        raise AutoCastError("auto-cast response contained zero valid assignments")

    result = _apply_assignments(project_id, valid)
    repo.set_status(
        job["id"],
        "complete",
        result={
            "received": len(payload),
            "applied": result["assigned"] + result["unassigned"],
            "assigned": result["assigned"],
            "unassigned": result["unassigned"],
        },
        message=(
            f"Assigned {result['assigned']} voices "
            f"({result['unassigned']} unassigned)"
        ),
    )
    log.info(
        "auto-cast job %s complete — assigned=%d unassigned=%d",
        job["id"],
        result["assigned"],
        result["unassigned"],
    )
