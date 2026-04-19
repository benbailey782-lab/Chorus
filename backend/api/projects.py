import re
import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.config import get_settings
from backend.db import connect
from backend.ingest.epub import ingest_epub
from backend.ingest.txt import ingest_txt
from backend.schemas import (
    ChapterDetail,
    ChapterOut,
    IngestResult,
    ProjectCreate,
    ProjectOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[-\s]+", "-", text)
    return text or "project"


def _unique_slug(base: str) -> str:
    with connect() as conn:
        slug = base
        n = 2
        while conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
            slug = f"{base}-{n}"
            n += 1
    return slug


def _project_out(row) -> ProjectOut:
    d = dict(row)
    with connect() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM chapters WHERE project_id=?", (d["id"],)
        ).fetchone()["c"]
    return ProjectOut(
        id=d["id"],
        slug=d["slug"],
        title=d["title"],
        author=d["author"],
        language=d["language"],
        status=d["status"],
        mode=d["mode"],
        pov_narrator_enabled=bool(d["pov_narrator_enabled"]),
        ambient_enabled=bool(d["ambient_enabled"]),
        cover_art_path=d["cover_art_path"],
        source_path=d["source_path"],
        total_duration_ms=d["total_duration_ms"],
        estimated_cost_usd=d["estimated_cost_usd"],
        actual_cost_usd=d["actual_cost_usd"],
        chapter_count=cnt,
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


@router.get("", response_model=List[ProjectOut])
def list_projects() -> List[ProjectOut]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [_project_out(r) for r in rows]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate) -> ProjectOut:
    pid = str(uuid.uuid4())
    slug = _unique_slug(_slugify(body.title))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, slug, title, author, language, mode)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pid, slug, body.title, body.author, body.language, body.mode),
        )
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()

    settings = get_settings()
    (settings.projects_path / slug).mkdir(parents=True, exist_ok=True)
    return _project_out(row)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "project not found")
    return _project_out(row)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, slug FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "project not found")
        conn.execute("DELETE FROM projects WHERE id=?", (row["id"],))
    proj_dir = get_settings().projects_path / row["slug"]
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


@router.get("/{project_id}/chapters", response_model=List[ChapterOut])
def list_chapters(project_id: str) -> List[ChapterOut]:
    with connect() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
        if not proj:
            raise HTTPException(404, "project not found")
        # LEFT JOIN a COUNT on segments so clients (e.g., Casting > Chapters
        # section) can show real per-chapter segment counts without N+1
        # round-trips to GET /api/chapters/{id}.
        rows = conn.execute(
            """
            SELECT c.*, COALESCE(s.cnt, 0) AS segment_count
            FROM chapters c
            LEFT JOIN (
                SELECT chapter_id, COUNT(*) AS cnt
                FROM segments
                GROUP BY chapter_id
            ) s ON s.chapter_id = c.id
            WHERE c.project_id = ?
            ORDER BY c.number
            """,
            (proj["id"],),
        ).fetchall()
    return [
        ChapterOut(
            id=r["id"],
            project_id=r["project_id"],
            number=r["number"],
            title=r["title"],
            word_count=r["word_count"],
            estimated_duration_ms=r["estimated_duration_ms"],
            status=r["status"],
            pov_character_id=r["pov_character_id"],
            ambient_scene_tag=r["ambient_scene_tag"],
            segment_count=r["segment_count"],
        )
        for r in rows
    ]


@router.get("/{project_id}/chapters/{number}", response_model=ChapterDetail)
def get_chapter(project_id: str, number: int) -> ChapterDetail:
    with connect() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
        if not proj:
            raise HTTPException(404, "project not found")
        row = conn.execute(
            "SELECT * FROM chapters WHERE project_id=? AND number=?",
            (proj["id"], number),
        ).fetchone()
    if not row:
        raise HTTPException(404, "chapter not found")
    return ChapterDetail(
        id=row["id"],
        project_id=row["project_id"],
        number=row["number"],
        title=row["title"],
        word_count=row["word_count"],
        estimated_duration_ms=row["estimated_duration_ms"],
        status=row["status"],
        pov_character_id=row["pov_character_id"],
        ambient_scene_tag=row["ambient_scene_tag"],
        raw_text=row["raw_text"],
    )


class ChapterTitleUpdate(BaseModel):
    title: str


@router.patch("/{project_id}/chapters/{number}/title", response_model=ChapterOut)
def update_chapter_title(project_id: str, number: int, body: ChapterTitleUpdate) -> ChapterOut:
    with connect() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
        if not proj:
            raise HTTPException(404, "project not found")
        conn.execute(
            "UPDATE chapters SET title=? WHERE project_id=? AND number=?",
            (body.title, proj["id"], number),
        )
        row = conn.execute(
            "SELECT * FROM chapters WHERE project_id=? AND number=?",
            (proj["id"], number),
        ).fetchone()
    if not row:
        raise HTTPException(404, "chapter not found")
    return ChapterOut(
        id=row["id"],
        project_id=row["project_id"],
        number=row["number"],
        title=row["title"],
        word_count=row["word_count"],
        estimated_duration_ms=row["estimated_duration_ms"],
        status=row["status"],
        pov_character_id=row["pov_character_id"],
        ambient_scene_tag=row["ambient_scene_tag"],
    )


@router.post("/{project_id}/ingest", response_model=IngestResult)
async def ingest(project_id: str, file: UploadFile = File(...)) -> IngestResult:
    with connect() as conn:
        proj = conn.execute(
            "SELECT * FROM projects WHERE id=? OR slug=?", (project_id, project_id)
        ).fetchone()
    if not proj:
        raise HTTPException(404, "project not found")

    filename = file.filename or "source"
    ext = Path(filename).suffix.lower().lstrip(".")
    raw = await file.read()

    if ext == "epub":
        result = ingest_epub(raw)
        source_kind = "epub"
    elif ext in {"txt", "text"}:
        result = ingest_txt(raw, filename=filename)
        source_kind = "txt"
    else:
        raise HTTPException(400, f"unsupported file type: {ext or 'unknown'}")

    settings = get_settings()
    proj_dir = settings.projects_path / proj["slug"]
    proj_dir.mkdir(parents=True, exist_ok=True)
    source_path = proj_dir / f"source.{ext}"
    source_path.write_bytes(raw)

    with connect() as conn:
        conn.execute(
            "DELETE FROM chapters WHERE project_id=?", (proj["id"],)
        )
        fields: list[str] = ["source_path=?", "updated_at=datetime('now')"]
        values: list = [str(source_path)]
        if result.title and not proj["title"].strip():
            fields.append("title=?")
            values.append(result.title)
        if result.author and not (proj["author"] or "").strip():
            fields.append("author=?")
            values.append(result.author)
        values.append(proj["id"])
        conn.execute(
            f"UPDATE projects SET {', '.join(fields)} WHERE id=?",
            values,
        )
        for ch in result.chapters:
            conn.execute(
                """
                INSERT INTO chapters
                    (id, project_id, number, title, raw_text, word_count, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    str(uuid.uuid4()),
                    proj["id"],
                    ch.number,
                    ch.title,
                    ch.text,
                    ch.word_count,
                ),
            )
        rows = conn.execute(
            "SELECT * FROM chapters WHERE project_id=? ORDER BY number",
            (proj["id"],),
        ).fetchall()

    chapters_out = [
        ChapterOut(
            id=r["id"],
            project_id=r["project_id"],
            number=r["number"],
            title=r["title"],
            word_count=r["word_count"],
            estimated_duration_ms=r["estimated_duration_ms"],
            status=r["status"],
            pov_character_id=r["pov_character_id"],
            ambient_scene_tag=r["ambient_scene_tag"],
        )
        for r in rows
    ]

    return IngestResult(
        project_id=proj["id"],
        source_kind=source_kind,
        title=result.title,
        author=result.author,
        chapters_detected=len(result.chapters),
        chapters=chapters_out,
        warnings=result.warnings,
    )
