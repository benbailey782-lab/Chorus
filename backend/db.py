import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.config import get_settings

SCHEMA_VERSION = 5

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    author TEXT,
    language TEXT NOT NULL DEFAULT 'en',
    status TEXT NOT NULL DEFAULT 'ingesting',
    mode TEXT NOT NULL DEFAULT 'automated',
    pov_narrator_enabled INTEGER NOT NULL DEFAULT 0,
    ambient_enabled INTEGER NOT NULL DEFAULT 1,
    cover_art_path TEXT,
    source_path TEXT,
    total_duration_ms INTEGER,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title TEXT,
    raw_text TEXT NOT NULL,
    pov_character_id TEXT,
    ambient_scene_tag TEXT,
    word_count INTEGER,
    estimated_duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(project_id, number)
);

CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id);

-- Characters (§9.3). Column names align with §9.3 where possible; the extra
-- fields (estimated_line_count tier, first_appearance_chapter) reflect the
-- validated extract_cast.md prompt output shape.
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    gender TEXT,
    age_estimate TEXT,
    description TEXT,
    speaking_style TEXT,
    character_archetype TEXT,
    first_appearance_chapter INTEGER,
    estimated_line_count TEXT,                      -- prompt output: main/supporting/minor/background
    line_count INTEGER,                             -- computed post-attribution (Phase 4)
    is_narrator INTEGER NOT NULL DEFAULT 0,
    voice_id TEXT,                                  -- FK → voices (soft; voice may be deleted)
    engine_override TEXT,
    notes TEXT,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id);

-- Voice library (§7.2). Mirrors the metadata schema exactly; arrays are stored
-- as JSON text columns per §9.4 ("stored in SQL with JSON columns for arrays").
CREATE TABLE IF NOT EXISTS voices (
    id TEXT PRIMARY KEY,
    voicebox_profile_id TEXT,
    display_name TEXT NOT NULL,
    gender TEXT,
    age_range TEXT,
    accent TEXT,
    tone_json TEXT NOT NULL DEFAULT '[]',
    timbre TEXT,
    pace TEXT,
    register TEXT,
    character_archetypes_json TEXT NOT NULL DEFAULT '[]',
    pool TEXT NOT NULL CHECK (pool IN ('narrator','main','background')),
    engine_preference TEXT,
    sample_text TEXT,
    source_notes TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    sample_audio_path TEXT,
    times_used INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_voices_pool ON voices(pool);

-- Segments (§9.5). Phase 4 rebuild: widens render_mode to the full §6
-- vocabulary, adds notes / voice_override_id / created_at / updated_at /
-- indexes, and tightens confidence to INTEGER (0-100) matching the prompt
-- output shape.
CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    character_id TEXT REFERENCES characters(id) ON DELETE SET NULL,
    order_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    render_mode TEXT NOT NULL DEFAULT 'prose'
        CHECK (render_mode IN (
            'prose','dialogue','epigraph','letter','poetry',
            'song_lyrics','emphasis','thought','chapter_heading'
        )),
    emotion_tags_json TEXT NOT NULL DEFAULT '[]',
    confidence INTEGER,
    notes TEXT,
    voice_override_id TEXT REFERENCES voices(id) ON DELETE SET NULL,
    audio_path TEXT,
    duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    text_modified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chapter_id, order_index)
);

CREATE INDEX IF NOT EXISTS idx_segments_chapter ON segments(chapter_id);
CREATE INDEX IF NOT EXISTS idx_segments_character ON segments(character_id);

CREATE TABLE IF NOT EXISTS pronunciations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    phonetic TEXT NOT NULL,
    ipa TEXT,
    confidence REAL,
    notes TEXT,
    UNIQUE(project_id, term)
);

CREATE TABLE IF NOT EXISTS playback_state (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL DEFAULT 1,
    position_ms INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Jobs (§9.8). ``kind`` == spec's ``type`` (kept for v1 compatibility).
-- ``status``: queued / running / awaiting_response / complete / failed.
-- ``awaiting_response`` is used by the file-drop LLM integration (§12A).
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0.0,
    message TEXT,
    payload_json TEXT,
    result_json TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def _db_file() -> Path:
    return Path(get_settings().db_path).resolve()


class MigrationAborted(RuntimeError):
    """Raised when a destructive migration would overwrite real user data."""


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply ordered migrations from the currently stored version to SCHEMA_VERSION.

    Each migration should be idempotent in its guard (check-then-act) so re-running
    init_db on an already-upgraded database is a no-op.
    """
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    current = row["version"] if row else 0

    if current >= SCHEMA_VERSION:
        return

    if current < 2:
        # Phase 0 shipped a placeholder voices table; Phase 2 replaces it with the
        # §7.2 schema. §7.4 guarantees no pre-cloned voices ship, so the table
        # should be empty — but abort loudly if somehow it isn't, so we never
        # silently drop real user data on a future migration.
        has_voices_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='voices'"
        ).fetchone()
        if has_voices_table:
            row_count = conn.execute("SELECT COUNT(*) AS c FROM voices").fetchone()["c"]
            if row_count > 0:
                raise MigrationAborted(
                    f"Refusing to migrate: `voices` table already has {row_count} row(s). "
                    "The Phase 2 schema (§7.2) is incompatible with the Phase 0 placeholder. "
                    "Back up data/chorus.db, drop the voices table manually after reviewing "
                    "its contents, and retry."
                )
            conn.execute("DROP TABLE voices")
        conn.executescript(SCHEMA_SQL)

    if current < 3:
        # Phase 3 aligns `characters` column names with spec §9.3 and adds job
        # lifecycle columns + a uniqueness constraint. No characters exist yet
        # (nothing writes to the table before Phase 3), but abort loudly if
        # rows are present so a future re-run on a populated DB doesn't
        # silently misplace columns.
        char_count = conn.execute(
            "SELECT COUNT(*) AS c FROM characters"
        ).fetchone()["c"]
        if char_count > 0:
            raise MigrationAborted(
                f"Refusing to migrate: `characters` table already has {char_count} row(s). "
                "The Phase 3 rename touches column names (archetype→character_archetype, "
                "assigned_voice_id→voice_id). Back up data/chorus.db and inspect the rows "
                "before retrying; the migration path for populated character tables has not "
                "been written."
            )
        conn.execute("DROP TABLE characters")
        conn.executescript(SCHEMA_SQL)

        # Jobs table: add new lifecycle columns in place. No risk to existing
        # rows — ALTER ADD COLUMN is non-destructive.
        existing_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "started_at" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN started_at TEXT")
        if "completed_at" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN completed_at TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    if current < 4:
        # Phase 4 rebuilds `segments` with the full §6 render_mode CHECK,
        # integer confidence, notes, voice_override_id, and timestamp columns.
        # Guard: abort if anything has written to segments already (dev DB is
        # empty; this is insurance for future re-runs on populated data).
        seg_count = conn.execute(
            "SELECT COUNT(*) AS c FROM segments"
        ).fetchone()["c"]
        if seg_count > 0:
            raise MigrationAborted(
                f"Refusing to migrate: `segments` table already has {seg_count} "
                "row(s). The Phase 4 rebuild changes render_mode CHECK + confidence "
                "type. Back up data/chorus.db and inspect the rows before retrying."
            )
        conn.execute("DROP TABLE segments")
        conn.executescript(SCHEMA_SQL)
        # chapters.pov_character_id was added in Phase 0 so this is a no-op
        # on an existing DB — but add-if-missing makes the migration
        # idempotent for hand-crafted test DBs.
        existing_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(chapters)").fetchall()
        }
        if "pov_character_id" not in existing_cols:
            conn.execute("ALTER TABLE chapters ADD COLUMN pov_character_id TEXT")

    if current < 5:
        # Phase 4 review UI: adds `segments.text_modified` so the UI can show a
        # "text edited" badge and keep re-renders deterministic. Additive
        # (ALTER ADD COLUMN) with a non-null default, so no data risk — runs
        # idempotently when re-applied.
        existing_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(segments)").fetchall()
        }
        if "text_modified" not in existing_cols:
            conn.execute(
                "ALTER TABLE segments ADD COLUMN text_modified INTEGER NOT NULL DEFAULT 0"
            )

    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    else:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def init_db() -> None:
    _db_file().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_file(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None
