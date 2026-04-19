"""Jobs table repository (§9.8).

``kind`` is the Chorus-internal name for spec §9.8's ``type`` column; the v1
schema used ``kind`` and we keep it for compatibility.

All functions operate on plain dicts. Callers dealing with JSON payloads and
results pass Python objects — this layer handles JSON (de)serialization at
the boundary.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Optional

from backend.db import connect

# Job kind vocabulary. Additions here should match §9.8's list.
JobKind = str
JobStatus = str

VALID_STATUSES = {"queued", "running", "awaiting_response", "complete", "failed"}

# When a job transitions into these statuses, record the timestamp.
_STARTED_STATUSES = {"running", "awaiting_response"}
_FINISHED_STATUSES = {"complete", "failed"}


def _row_to_job(row) -> dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json")) if d.get("payload_json") else None
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    return d


def create_job(
    *,
    project_id: Optional[str],
    kind: JobKind,
    payload: Optional[dict[str, Any]] = None,
    status: JobStatus = "queued",
    message: Optional[str] = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid job status {status!r}")
    job_id = str(uuid.uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    started_at_sql = "datetime('now')" if status in _STARTED_STATUSES else "NULL"
    with connect() as conn:
        conn.execute(
            f"""
            INSERT INTO jobs (id, project_id, kind, status, payload_json, message, started_at)
            VALUES (?, ?, ?, ?, ?, ?, {started_at_sql})
            """,
            (job_id, project_id, kind, status, payload_json, message),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(
    *,
    project_id: Optional[str] = None,
    kinds: Optional[Iterable[str]] = None,
    statuses: Optional[Iterable[str]] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if project_id is not None:
        where.append("project_id = ?")
        params.append(project_id)
    if kinds:
        kinds_list = list(kinds)
        where.append(f"kind IN ({','.join(['?'] * len(kinds_list))})")
        params.extend(kinds_list)
    if statuses:
        status_list = list(statuses)
        where.append(f"status IN ({','.join(['?'] * len(status_list))})")
        params.extend(status_list)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY datetime(created_at) DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_job(r) for r in rows]


def list_awaiting(*, kinds: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
    """Jobs currently parked on ``awaiting_response`` — what the worker polls."""
    return list_jobs(kinds=kinds, statuses=["awaiting_response"], limit=1000)


def set_status(
    job_id: str,
    status: JobStatus,
    *,
    error: Optional[str] = None,
    result: Optional[Any] = None,
    message: Optional[str] = None,
    progress: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Transition a job to ``status`` and update auxiliary fields.

    Automatically sets ``started_at`` on first entry into a running/awaiting
    status, and ``completed_at`` on entry into complete/failed. Idempotent:
    writing the same terminal status twice won't overwrite an existing
    ``completed_at``.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid job status {status!r}")

    sets: list[str] = ["status = ?", "updated_at = datetime('now')"]
    params: list[Any] = [status]
    if error is not None:
        sets.append("error = ?")
        params.append(error)
    elif status != "failed":
        # Clear stale errors on successful progression.
        sets.append("error = NULL")
    if result is not None:
        sets.append("result_json = ?")
        params.append(json.dumps(result, ensure_ascii=False))
    if message is not None:
        sets.append("message = ?")
        params.append(message)
    if progress is not None:
        sets.append("progress = ?")
        params.append(float(progress))
    if status in _STARTED_STATUSES:
        sets.append("started_at = COALESCE(started_at, datetime('now'))")
    if status in _FINISHED_STATUSES:
        sets.append("completed_at = COALESCE(completed_at, datetime('now'))")
        if status == "complete" and progress is None:
            sets.append("progress = 100.0")

    params.append(job_id)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params)
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None
