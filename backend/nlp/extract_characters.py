"""Pass 1 — Cast Extraction (§10.1) via file-drop (§12A).

``trigger`` kicks off a file-drop request; the companion Claude Code session
executes the prompt and drops ``response_<id>.json``; the jobs worker calls
:func:`handle_response` which validates and inserts rows into ``characters``.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from backend.config import get_settings
from backend.db import connect
from backend.jobs import repo, worker
from backend.nlp import file_drop, render

log = logging.getLogger(__name__)

JOB_KIND = "extract_characters"
PROMPT_NAME = "extract_cast.md"

# Fields §10.1's prompt output guarantees. Missing any of these is a reason to
# fail the whole response — Chorus shouldn't insert half-populated rows.
REQUIRED_FIELDS = (
    "name",
    "gender",
    "age_estimate",
    "description",
    "speaking_style",
    "character_archetype",
    "estimated_line_count",
)


class ExtractCastError(RuntimeError):
    """Raised when cast extraction can't be triggered or ingested."""


@dataclass
class ExtractCastTriggerResult:
    job_id: str
    request_path: str
    book_text_chars: int
    truncated: bool
    warnings: list[str]


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def _gather_book_text(project_id: str) -> tuple[str, int, bool, list[str]]:
    """Concatenate every chapter's raw_text. Returns (text, total_chars, truncated, warnings).

    Truncates at ``settings.extract_cast_char_limit`` and appends a warning.
    """
    settings = get_settings()
    with connect() as conn:
        rows = conn.execute(
            "SELECT number, title, raw_text FROM chapters WHERE project_id=? ORDER BY number",
            (project_id,),
        ).fetchall()
    if not rows:
        raise ExtractCastError(
            "project has no chapters yet — ingest a source file before extracting cast"
        )

    parts: list[str] = []
    for r in rows:
        title = (r["title"] or f"Chapter {r['number']}").strip()
        parts.append(f"## {title}\n\n{r['raw_text']}")
    full = "\n\n".join(parts).strip()

    total_chars = len(full)
    limit = settings.extract_cast_char_limit
    warnings: list[str] = []
    truncated = False
    if total_chars > limit:
        full = full[:limit]
        truncated = True
        warnings.append(
            "For best results, use an EPUB containing a single book. This "
            f"bundle contains more text than can be processed in one pass; "
            f"only the first {limit:,} chars (of {total_chars:,}) will be "
            "included in cast extraction."
        )
    return full, total_chars, truncated, warnings


async def trigger(project_id: str) -> ExtractCastTriggerResult:
    """Render the extract-cast prompt, create the job, write the request file."""
    with connect() as conn:
        proj = conn.execute(
            "SELECT * FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
    if not proj:
        raise ExtractCastError(f"project {project_id!r} not found")

    book_text, total_chars, truncated, warnings = _gather_book_text(proj["id"])
    prompt_text = render.load_prompt(PROMPT_NAME, {"BOOK_TEXT": book_text})

    job = repo.create_job(
        project_id=proj["id"],
        kind=JOB_KIND,
        payload={
            "book_text_chars_submitted": len(book_text),
            "book_text_chars_total": total_chars,
            "truncated": truncated,
            "warnings": warnings,
        },
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
            "book_text_chars": len(book_text),
        },
    )
    log.info(
        "extract-cast job %s queued (project=%s, %d chars%s)",
        job["id"],
        proj["slug"],
        len(book_text),
        " — truncated" if truncated else "",
    )
    return ExtractCastTriggerResult(
        job_id=job["id"],
        request_path=str(path),
        book_text_chars=len(book_text),
        truncated=truncated,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Response ingestion (called by the jobs worker)
# ---------------------------------------------------------------------------


def _validate_entries(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return [], [f"expected a JSON array, got {type(payload).__name__}"]
    valid: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            errors.append(f"entry #{idx}: not a JSON object")
            continue
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            errors.append(f"entry #{idx} ({entry.get('name', '?')!r}): missing {missing}")
            continue
        name = str(entry["name"]).strip()
        if not name:
            errors.append(f"entry #{idx}: empty name")
            continue
        if name.lower() in seen_names:
            errors.append(f"entry #{idx}: duplicate name {name!r}")
            continue
        seen_names.add(name.lower())
        valid.append(entry)
    return valid, errors


def _insert_characters(project_id: str, entries: list[dict[str, Any]]) -> int:
    with connect() as conn:
        # Clear any previous extraction — re-running replaces the cast.
        conn.execute("DELETE FROM characters WHERE project_id=?", (project_id,))
        for entry in entries:
            aliases = entry.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            is_narrator = 1 if str(entry["name"]).lower() == "narrator" else 0
            conn.execute(
                """
                INSERT INTO characters (
                    id, project_id, name, aliases_json, gender, age_estimate,
                    description, speaking_style, character_archetype,
                    first_appearance_chapter, estimated_line_count,
                    is_narrator, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    entry["name"],
                    json.dumps(aliases, ensure_ascii=False),
                    entry.get("gender"),
                    entry.get("age_estimate"),
                    entry.get("description"),
                    entry.get("speaking_style"),
                    entry.get("character_archetype"),
                    entry.get("first_appearance_chapter"),
                    entry.get("estimated_line_count"),
                    is_narrator,
                    entry.get("notes"),
                ),
            )
        conn.execute(
            "UPDATE projects SET status=?, updated_at=datetime('now') WHERE id=?",
            ("casting", project_id),
        )
    return len(entries)


@worker.register_handler(JOB_KIND)
async def handle_response(job: dict[str, Any], payload: Any) -> None:
    project_id: Optional[str] = job.get("project_id")
    if not project_id:
        raise ExtractCastError("job has no project_id")

    valid, errors = _validate_entries(payload)
    if errors:
        joined = "; ".join(errors[:8])
        more = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
        raise ExtractCastError(f"cast response failed validation: {joined}{more}")
    if not valid:
        raise ExtractCastError("cast response contained zero characters")

    inserted = _insert_characters(project_id, valid)
    repo.set_status(
        job["id"],
        "complete",
        result={"inserted": inserted, "received": len(payload)},
        message=f"Inserted {inserted} characters",
    )
    log.info("extract-cast job %s complete — %d characters", job["id"], inserted)
