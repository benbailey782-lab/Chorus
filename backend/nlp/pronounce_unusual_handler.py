"""Pass 3 — Pronunciation extraction (§10.3) via file-drop (§12A).

``trigger`` renders ``pronounce_unusual.md`` with the project's cast + book
text and drops a request file. The file-drop worker calls :func:`handle` when
the companion session drops a response JSON; validated rows are inserted (or
updated on UNIQUE conflict) into the project-scoped ``pronunciations`` table.

Key field mapping between the prompt's output vocabulary and the DB columns:

    word        -> term
    respelling  -> phonetic
    ipa         -> ipa
    category    -> category (normalized to the Literal set)
    confidence  -> confidence
    notes       -> notes

The row is stamped ``source = 'pass3'`` so promotion / manual-origin rows can
be distinguished in the UI.
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

JOB_KIND = "pronounce_unusual"
PROMPT_NAME = "pronounce_unusual.md"

VALID_CATEGORIES = {
    "character_name", "place", "proper_noun", "phrase", "other",
}

# Fields the handler will tolerate from the prompt — mapping is applied in
# ``_normalize_entry``. Missing ``word`` or ``respelling`` is a hard fail.
REQUIRED_FIELDS = ("word", "respelling")


class PronounceUnusualError(RuntimeError):
    """Raised when pass-3 extraction can't be triggered or ingested."""


@dataclass
class PronounceUnusualTriggerResult:
    job_id: str
    request_path: str
    book_text_chars: int
    truncated: bool
    cast_size: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def _build_cast_json(project_id: str) -> list[dict[str, Any]]:
    """Slim cast shape for pronunciation extraction — name + archetype only."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT name, character_archetype, is_narrator
            FROM characters WHERE project_id=? ORDER BY name
            """,
            (project_id,),
        ).fetchall()
    cast: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["is_narrator"] = bool(d.get("is_narrator"))
        cast.append(d)
    return cast


def _gather_book_text(project_id: str) -> tuple[str, int, bool, list[str]]:
    """Concatenate chapter text with the same truncation policy as extract-cast."""
    settings = get_settings()
    with connect() as conn:
        rows = conn.execute(
            "SELECT number, title, raw_text FROM chapters WHERE project_id=? ORDER BY number",
            (project_id,),
        ).fetchall()
    if not rows:
        raise PronounceUnusualError(
            "project has no chapters yet — ingest a source before extracting pronunciations"
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
            f"Book text truncated to {limit:,} chars (of {total_chars:,}) "
            "for pronunciation extraction."
        )
    return full, total_chars, truncated, warnings


async def trigger(project_id: str) -> PronounceUnusualTriggerResult:
    """Render the pronounce-unusual prompt, create the job, write the request file."""
    with connect() as conn:
        proj = conn.execute(
            "SELECT * FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
    if not proj:
        raise PronounceUnusualError(f"project {project_id!r} not found")

    cast = _build_cast_json(proj["id"])
    if not cast:
        raise PronounceUnusualError(
            "project has no cast yet — run extract-cast before extracting pronunciations"
        )

    book_text, total_chars, truncated, warnings = _gather_book_text(proj["id"])
    prompt_text = render.load_prompt(
        PROMPT_NAME,
        {
            "CAST_JSON": json.dumps(cast, ensure_ascii=False, indent=2),
            "BOOK_TEXT": book_text,
        },
    )

    job = repo.create_job(
        project_id=proj["id"],
        kind=JOB_KIND,
        payload={
            "book_text_chars_submitted": len(book_text),
            "book_text_chars_total": total_chars,
            "truncated": truncated,
            "cast_size": len(cast),
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
            "cast_size": len(cast),
        },
    )
    log.info(
        "pronounce-unusual job %s queued (project=%s, %d chars%s, cast=%d)",
        job["id"],
        proj["slug"],
        len(book_text),
        " — truncated" if truncated else "",
        len(cast),
    )
    return PronounceUnusualTriggerResult(
        job_id=job["id"],
        request_path=str(path),
        book_text_chars=len(book_text),
        truncated=truncated,
        cast_size=len(cast),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Response ingestion
# ---------------------------------------------------------------------------


def _normalize_category(raw: Any) -> Optional[str]:
    """Squash legacy harness categories into the Chorus-allowed set."""
    if raw is None:
        return None
    cat = str(raw).strip().lower()
    if cat in VALID_CATEGORIES:
        return cat
    # Legacy/harness vocabulary → canonical mapping
    legacy = {
        "place_name": "place",
        "foreign_phrase": "phrase",
        "title_honorific": "proper_noun",
        "other_proper_noun": "proper_noun",
        "invented_term": "other",
    }
    return legacy.get(cat, "other")


def _normalize_entry(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map a single prompt entry into a DB-shaped dict or return None if invalid."""
    missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
    if missing:
        return None
    term = str(entry["word"]).strip()
    phonetic = str(entry["respelling"]).strip()
    if not term or not phonetic:
        return None
    confidence: Optional[float]
    raw_conf = entry.get("confidence")
    try:
        confidence = float(raw_conf) if raw_conf is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        confidence = max(0.0, min(100.0, confidence))
    return {
        "term": term,
        "phonetic": phonetic,
        "ipa": (str(entry["ipa"]).strip() if entry.get("ipa") else None),
        "category": _normalize_category(entry.get("category")),
        "confidence": confidence,
        "notes": (str(entry["notes"]).strip() if entry.get("notes") else None),
    }


def _validate_entries(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return [], [f"expected a JSON array, got {type(payload).__name__}"]
    valid: list[dict[str, Any]] = []
    seen_terms: set[str] = set()
    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            errors.append(f"entry #{idx}: not a JSON object")
            continue
        norm = _normalize_entry(entry)
        if norm is None:
            errors.append(
                f"entry #{idx}: missing required fields (word, respelling) "
                f"or empty — got keys {sorted(entry.keys())}"
            )
            continue
        # Case-insensitive dedupe within a single response; later duplicates
        # overwrite earlier ones (newer output wins), matching the DB upsert.
        key = norm["term"].lower()
        if key in seen_terms:
            # Replace earlier match with this one.
            valid = [v for v in valid if v["term"].lower() != key]
        seen_terms.add(key)
        valid.append(norm)
    return valid, errors


def _upsert_pronunciation(
    conn, project_id: str, entry: dict[str, Any]
) -> tuple[str, bool]:
    """Insert a new pronunciation or update the existing row on UNIQUE conflict.

    Returns (row_id, inserted) — ``inserted`` is False when an existing row
    for (project_id, term) was updated instead.
    """
    existing = conn.execute(
        "SELECT id FROM pronunciations WHERE project_id=? AND term=? COLLATE NOCASE",
        (project_id, entry["term"]),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE pronunciations
            SET phonetic=?, ipa=?, category=?, confidence=?, notes=?, source=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                entry["phonetic"],
                entry["ipa"],
                entry["category"],
                entry["confidence"],
                entry["notes"],
                "pass3",
                existing["id"],
            ),
        )
        return existing["id"], False
    row_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO pronunciations (
            id, project_id, term, phonetic, ipa, confidence, category, notes, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            project_id,
            entry["term"],
            entry["phonetic"],
            entry["ipa"],
            entry["confidence"],
            entry["category"],
            entry["notes"],
            "pass3",
        ),
    )
    return row_id, True


@worker.register_handler(JOB_KIND)
async def handle(job: dict[str, Any], payload: Any) -> None:
    project_id: Optional[str] = job.get("project_id")
    if not project_id:
        raise PronounceUnusualError("job has no project_id")

    valid, errors = _validate_entries(payload)
    if errors and not valid:
        # If nothing salvageable, fail loudly so the operator can fix & re-drop.
        joined = "; ".join(errors[:8])
        more = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
        raise PronounceUnusualError(
            f"pronunciations response failed validation: {joined}{more}"
        )

    inserted = 0
    updated = 0
    with connect() as conn:
        for entry in valid:
            _, was_insert = _upsert_pronunciation(conn, project_id, entry)
            if was_insert:
                inserted += 1
            else:
                updated += 1
                log.info(
                    "pronounce-unusual: updated existing (project=%s term=%r)",
                    project_id, entry["term"],
                )

    repo.set_status(
        job["id"],
        "complete",
        result={
            "inserted": inserted,
            "updated": updated,
            "received": len(payload) if isinstance(payload, list) else 0,
            "validation_errors": errors,
        },
        message=f"Pronunciations: inserted {inserted}, updated {updated}",
    )
    log.info(
        "pronounce-unusual job %s complete — inserted=%d updated=%d errors=%d",
        job["id"], inserted, updated, len(errors),
    )
