"""Jobs API (§16).

Endpoints:
  * ``GET /api/jobs/{id}``                — single job row
  * ``GET /api/projects/{id}/jobs``       — list for a project, optional
    ``?status=awaiting_response`` and ``?kind=extract_characters`` filters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db import connect
from backend.jobs import repo
from backend.schemas import JobOut, JobStatusValue

router = APIRouter(prefix="/api", tags=["jobs"])


def _to_out(job: dict) -> JobOut:
    return JobOut(
        id=job["id"],
        project_id=job.get("project_id"),
        kind=job["kind"],
        status=job["status"],
        progress=job.get("progress") or 0.0,
        message=job.get("message"),
        payload=job.get("payload"),
        result=job.get("result"),
        error=job.get("error"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        created_at=job["created_at"],
        updated_at=job["updated_at"],
    )


def _resolve_project_id(id_or_slug: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (id_or_slug, id_or_slug)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"project {id_or_slug!r} not found")
    return row["id"]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(404, f"job {job_id!r} not found")
    return _to_out(job)


@router.get("/projects/{id_or_slug}/jobs", response_model=list[JobOut])
def list_project_jobs(
    id_or_slug: str,
    status: Optional[JobStatusValue] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    include_old_failures: bool = Query(default=False),
) -> list[JobOut]:
    project_id = _resolve_project_id(id_or_slug)
    jobs = repo.list_jobs(
        project_id=project_id,
        kinds=[kind] if kind else None,
        statuses=[status] if status else None,
        limit=limit,
    )
    if not include_old_failures:
        # Hide stale assembly failures from the default project jobs list.
        # Context: Phase 6 shipped with a Windows asyncio bug where
        # `asyncio.create_subprocess_exec` failed under the default
        # SelectorEventLoop, leaving many `assemble_chapter` jobs stuck in
        # `failed`. The bug was fixed in phase6-fix/phase6-fix3 (see
        # `backend/main.py` + `backend/main_serve.py` setting
        # `WindowsProactorEventLoopPolicy`), but the old rows persist in the
        # `jobs` table and clutter PendingJobsBanner on every project page.
        # Strategy: hide `assemble_chapter` failures older than 5 minutes by
        # default. Live failures (<5 min) still surface so the operator sees
        # real problems. Passing `?include_old_failures=true` returns
        # everything for debug inspection.
        #
        # `updated_at` is stored as SQLite `datetime('now')` text, which is
        # UTC ISO-ish ("YYYY-MM-DD HH:MM:SS"). ISO 8601 timestamps sort
        # chronologically as strings, so a lexical `<` comparison against a
        # threshold string is correct without parsing every row.
        threshold_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
        threshold_str = threshold_dt.strftime("%Y-%m-%d %H:%M:%S")
        jobs = [
            j
            for j in jobs
            if not (
                j.get("kind") == "assemble_chapter"
                and j.get("status") == "failed"
                and (j.get("updated_at") or "") < threshold_str
            )
        ]
    return [_to_out(j) for j in jobs]
