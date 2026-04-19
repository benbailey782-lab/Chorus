"""Jobs API (§16).

Endpoints:
  * ``GET /api/jobs/{id}``                — single job row
  * ``GET /api/projects/{id}/jobs``       — list for a project, optional
    ``?status=awaiting_response`` and ``?kind=extract_characters`` filters.
"""

from __future__ import annotations

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
) -> list[JobOut]:
    project_id = _resolve_project_id(id_or_slug)
    jobs = repo.list_jobs(
        project_id=project_id,
        kinds=[kind] if kind else None,
        statuses=[status] if status else None,
        limit=limit,
    )
    return [_to_out(j) for j in jobs]
