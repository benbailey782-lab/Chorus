import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.config import get_settings

SCHEMA_VERSION = 8

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
    generation_config_json TEXT,
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
-- Phase 5 remediation (v8): adds voicebox_engine + voicebox_effect_preset_id for
-- per-voice TTS engine selection and effect-preset assignment. The CHECK
-- constraint on voicebox_engine applies to fresh-create only (via this
-- SCHEMA_SQL) — SQLite can't ADD COLUMN with CHECK, so existing databases
-- upgraded via the v7→v8 migration rely on the Pydantic Literal to enforce
-- the allowed engine set at the application layer.
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
    voicebox_engine TEXT NOT NULL DEFAULT 'qwen3-tts'
        CHECK (voicebox_engine IN (
            'qwen3-tts','luxtts','chatterbox-multilingual',
            'chatterbox-turbo','humeai-tada','kokoro-82m','qwen-custom-voice'
        )),
    voicebox_effect_preset_id TEXT,
    times_used INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_voices_pool ON voices(pool);

-- Voice samples (Phase 5 remediation). Multi-sample support per voice — the
-- original voices.sample_audio_path is backfilled as the first entry labelled
-- 'Original' during the v7→v8 migration; new samples are added via
-- POST /api/voices/{id}/samples (Phase 5 remediation commit 4).
-- voicebox_sample_id is null until the sample is synced with a Voicebox
-- profile via the add-sample-to-profile endpoint.
CREATE TABLE IF NOT EXISTS voice_samples (
    id TEXT PRIMARY KEY,
    voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
    sample_path TEXT NOT NULL,
    voicebox_sample_id TEXT,
    label TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (voice_id, sample_path)
);

CREATE INDEX IF NOT EXISTS idx_voice_samples_voice_id ON voice_samples(voice_id);

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
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','generating','generated','approved','error')),
    text_modified INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    voicebox_generation_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chapter_id, order_index)
);

CREATE INDEX IF NOT EXISTS idx_segments_chapter ON segments(chapter_id);
CREATE INDEX IF NOT EXISTS idx_segments_character ON segments(character_id);

-- TODO(phase-7): add applies_to_character_id TEXT REFERENCES characters(id) for per-character pronunciation scoping (spec §9.6).
CREATE TABLE IF NOT EXISTS pronunciations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    phonetic TEXT NOT NULL,
    ipa TEXT,
    confidence REAL,
    category TEXT,
    notes TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, term)
);

-- Global pronunciations library (§9.6). Term is case-insensitive unique so
-- "Tyrion" and "tyrion" map to the same entry. `term` + `phonetic` match the
-- project-scoped pronunciations table for consistency; the pronounce_unusual
-- prompt's word/respelling vocabulary is mapped in the handler.
CREATE TABLE IF NOT EXISTS pronunciations_global (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phonetic TEXT NOT NULL,
    ipa TEXT,
    confidence REAL,
    category TEXT,
    notes TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pronunciations_global_term ON pronunciations_global(term COLLATE NOCASE);

-- Playback state (§9.7). Single row per project; Phase 6 rebuild swaps
-- `chapter_number` for chapter_id/current_segment_id UUID references and
-- adds a `speed` control bounded to the UI's allowed range.
CREATE TABLE IF NOT EXISTS playback_state (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    current_segment_id TEXT REFERENCES segments(id) ON DELETE SET NULL,
    position_ms INTEGER NOT NULL DEFAULT 0,
    speed REAL NOT NULL DEFAULT 1.0 CHECK (speed >= 0.25 AND speed <= 4.0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Chapter assemblies (Phase 6). One row per chapter once the per-segment
-- audio has been concatenated into a single file; `segment_hash` is the
-- cache key (re-derived from segment ids + durations + approved/raw state).
CREATE TABLE IF NOT EXISTS chapter_assemblies (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL UNIQUE REFERENCES chapters(id) ON DELETE CASCADE,
    audio_path TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    segment_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chapter_assemblies_chapter_id ON chapter_assemblies(chapter_id);

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

    if current < 6:
        # Phase 5: TTS generation + pronunciation overrides.
        # 1. Create pronunciations_global (new, case-insensitive unique on term).
        # 2. Extend pronunciations with category/source/created_at/updated_at.
        # 3. Extend projects with generation_config_json.
        # 4. Rebuild segments to add CHECK on status + approved_at column.
        #    SQLite can't add a CHECK to an existing column without a table
        #    rebuild, so we follow the v4 pattern: create new table, copy rows,
        #    drop old, rename. Preserves ALL rows. If any existing status value
        #    falls outside the allowed set, abort with MigrationAborted naming
        #    the offending row.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pronunciations_global (
                id TEXT PRIMARY KEY,
                term TEXT NOT NULL UNIQUE COLLATE NOCASE,
                phonetic TEXT NOT NULL,
                ipa TEXT,
                confidence REAL,
                category TEXT,
                notes TEXT,
                source TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pronunciations_global_term "
            "ON pronunciations_global(term COLLATE NOCASE)"
        )

        pron_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(pronunciations)").fetchall()
        }
        if "category" not in pron_cols:
            conn.execute("ALTER TABLE pronunciations ADD COLUMN category TEXT")
        if "source" not in pron_cols:
            conn.execute("ALTER TABLE pronunciations ADD COLUMN source TEXT")
        if "created_at" not in pron_cols:
            conn.execute(
                "ALTER TABLE pronunciations ADD COLUMN created_at TEXT "
                "NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        if "updated_at" not in pron_cols:
            conn.execute(
                "ALTER TABLE pronunciations ADD COLUMN updated_at TEXT "
                "NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )

        proj_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "generation_config_json" not in proj_cols:
            conn.execute(
                "ALTER TABLE projects ADD COLUMN generation_config_json TEXT"
            )

        # Segments rebuild: formal status CHECK + approved_at.
        allowed_statuses = (
            "pending", "generating", "generated", "approved", "error",
        )
        invalid_rows = conn.execute(
            f"""
            SELECT id, status FROM segments
            WHERE status NOT IN ({','.join('?' * len(allowed_statuses))})
            LIMIT 1
            """,
            allowed_statuses,
        ).fetchall()
        if invalid_rows:
            bad = invalid_rows[0]
            raise MigrationAborted(
                f"Refusing to migrate: segment row id={bad['id']} has status="
                f"{bad['status']!r}, which is outside the new CHECK set "
                f"{allowed_statuses}. Inspect and coerce the row manually "
                "(e.g. UPDATE segments SET status='pending' WHERE id=...) "
                "before retrying."
            )

        seg_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(segments)").fetchall()
        }
        # approved_at may already exist if someone hand-patched; rebuild still
        # runs because it's the only way to add the status CHECK.
        has_approved_at = "approved_at" in seg_cols

        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                CREATE TABLE segments_new (
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
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','generating','generated','approved','error')),
                    text_modified INTEGER NOT NULL DEFAULT 0,
                    approved_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(chapter_id, order_index)
                )
                """
            )
            approved_at_select = "approved_at" if has_approved_at else "NULL"
            conn.execute(
                f"""
                INSERT INTO segments_new (
                    id, chapter_id, character_id, order_index, text, render_mode,
                    emotion_tags_json, confidence, notes, voice_override_id,
                    audio_path, duration_ms, status, text_modified, approved_at,
                    created_at, updated_at
                )
                SELECT
                    id, chapter_id, character_id, order_index, text, render_mode,
                    emotion_tags_json, confidence, notes, voice_override_id,
                    audio_path, duration_ms, status, text_modified, {approved_at_select},
                    created_at, updated_at
                FROM segments
                """
            )
            conn.execute("DROP TABLE segments")
            conn.execute("ALTER TABLE segments_new RENAME TO segments")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_chapter ON segments(chapter_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_character ON segments(character_id)"
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    if current < 7:
        # Phase 6: Player + Playback UI.
        # 1. Rebuild playback_state: drop chapter_number (numeric), add
        #    chapter_id (UUID FK), current_segment_id (UUID FK), speed
        #    (bounded REAL). Keep project_id PK + position_ms + updated_at.
        #    We can't resolve chapter_number → chapter_id without project
        #    context inside the migration, so legacy rows migrate with
        #    chapter_id=NULL; the UI will fall back to chapter 1 on first
        #    open. In the expected dev-DB case the table is empty anyway.
        # 2. Create chapter_assemblies (new, one row per chapter).
        import logging
        log = logging.getLogger(__name__)

        existing_playback = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='playback_state'"
        ).fetchone()

        conn.execute("BEGIN")
        try:
            if existing_playback:
                legacy_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM playback_state"
                ).fetchone()["c"]
                if legacy_count > 0:
                    log.info(
                        "phase6 migration: preserving %d playback_state row(s); "
                        "chapter_number will be dropped (chapter_id set NULL).",
                        legacy_count,
                    )
                conn.execute("ALTER TABLE playback_state RENAME TO playback_state_old")
            conn.execute(
                """
                CREATE TABLE playback_state (
                    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                    chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
                    current_segment_id TEXT REFERENCES segments(id) ON DELETE SET NULL,
                    position_ms INTEGER NOT NULL DEFAULT 0,
                    speed REAL NOT NULL DEFAULT 1.0 CHECK (speed >= 0.25 AND speed <= 4.0),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            if existing_playback:
                # Best-effort migration: preserve project_id / position_ms /
                # updated_at; leave chapter_id + current_segment_id NULL and
                # accept the default speed (1.0).
                conn.execute(
                    """
                    INSERT INTO playback_state (
                        project_id, chapter_id, current_segment_id,
                        position_ms, speed, updated_at
                    )
                    SELECT
                        project_id, NULL, NULL,
                        COALESCE(position_ms, 0), 1.0,
                        COALESCE(updated_at, CURRENT_TIMESTAMP)
                    FROM playback_state_old
                    """
                )
                conn.execute("DROP TABLE playback_state_old")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chapter_assemblies (
                    id TEXT PRIMARY KEY,
                    chapter_id TEXT NOT NULL UNIQUE REFERENCES chapters(id) ON DELETE CASCADE,
                    audio_path TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    segment_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chapter_assemblies_chapter_id "
                "ON chapter_assemblies(chapter_id)"
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    if current < 8:
        # Phase 5 remediation: Voicebox-parity schema additions.
        # 1. voices.voicebox_engine — per-voice TTS engine selection (default
        #    'qwen3-tts'). SQLite can't ADD COLUMN with a CHECK constraint, so
        #    the allowed-set enforcement on existing DBs lives in the Pydantic
        #    `VoiceboxEngine` Literal. Fresh databases (via SCHEMA_SQL) include
        #    the CHECK at table-create time.
        # 2. voices.voicebox_effect_preset_id — nullable reference to a
        #    Voicebox-side effect preset id.
        # 3. segments.voicebox_generation_id — nullable, tracks which Voicebox
        #    generation produced the current audio (for version history).
        #    Column doesn't exist on v7 DBs, so the "abort if rows have a
        #    non-null value" defensive check naturally can't run — any existing
        #    rows get NULL on ADD COLUMN, which is correct.
        # 4. voice_samples — new table for multi-sample-per-voice support.
        # 5. Backfill voice_samples from voices.sample_audio_path (labelled
        #    'Original'). Python-side UUIDs match the rest of the codebase.
        voice_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(voices)").fetchall()
        }
        if "voicebox_engine" not in voice_cols:
            conn.execute(
                "ALTER TABLE voices ADD COLUMN voicebox_engine TEXT "
                "NOT NULL DEFAULT 'qwen3-tts'"
            )
        if "voicebox_effect_preset_id" not in voice_cols:
            conn.execute(
                "ALTER TABLE voices ADD COLUMN voicebox_effect_preset_id TEXT"
            )

        seg_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(segments)").fetchall()
        }
        if "voicebox_generation_id" not in seg_cols:
            conn.execute(
                "ALTER TABLE segments ADD COLUMN voicebox_generation_id TEXT"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_samples (
                id TEXT PRIMARY KEY,
                voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
                sample_path TEXT NOT NULL,
                voicebox_sample_id TEXT,
                label TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (voice_id, sample_path)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_samples_voice_id "
            "ON voice_samples(voice_id)"
        )

        # Backfill: every voice with a non-empty sample_audio_path gets a
        # voice_samples row labelled 'Original'. INSERT OR IGNORE makes the
        # migration re-runnable (the UNIQUE (voice_id, sample_path) constraint
        # blocks duplicates on repeated runs).
        rows = conn.execute(
            "SELECT id, sample_audio_path, added_at FROM voices "
            "WHERE sample_audio_path IS NOT NULL AND sample_audio_path != ''"
        ).fetchall()
        for row_ in rows:
            vsid = str(uuid.uuid4())
            conn.execute(
                "INSERT OR IGNORE INTO voice_samples "
                "(id, voice_id, sample_path, label, created_at) "
                "VALUES (?, ?, ?, 'Original', ?)",
                (vsid, row_["id"], row_["sample_audio_path"], row_["added_at"])
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
