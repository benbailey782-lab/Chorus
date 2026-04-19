"""Voice library CRUD + filtering.

Matches the §7.2 metadata schema 1:1. Arrays (tone, character_archetypes, tags)
are stored as JSON strings in SQLite per §9.4 and hydrated back into lists at
the boundary of this module — callers get plain dicts with real lists.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.config import get_settings
from backend.db import connect

VOICE_ID_PREFIX = "v_"

# Columns we persist as JSON arrays
_JSON_ARRAY_COLUMNS = ("tone_json", "character_archetypes_json", "tags_json")


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[-\s]+", "_", text)
    return text or "voice"


def _new_voice_id(display_name: str) -> str:
    slug = _slugify(display_name)[:32]
    suffix = uuid.uuid4().hex[:6]
    return f"{VOICE_ID_PREFIX}{slug}_{suffix}"


def _dumps(value: Optional[Iterable[str]]) -> str:
    return json.dumps(list(value or []), ensure_ascii=False)


def _loads(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed]


def _row_to_voice(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # voicebox_engine / voicebox_effect_preset_id were added in v8
    # (Phase-5 remediation Commit 1). _row_get tolerates pre-v8 rows
    # surfacing through tests with old fixtures.
    return {
        "id": d["id"],
        "voicebox_profile_id": d["voicebox_profile_id"],
        "display_name": d["display_name"],
        "gender": d["gender"],
        "age_range": d["age_range"],
        "accent": d["accent"],
        "tone": _loads(d["tone_json"]),
        "timbre": d["timbre"],
        "pace": d["pace"],
        "register": d["register"],
        "character_archetypes": _loads(d["character_archetypes_json"]),
        "pool": d["pool"],
        "engine_preference": d["engine_preference"],
        "sample_text": d["sample_text"],
        "source_notes": d["source_notes"],
        "tags": _loads(d["tags_json"]),
        "sample_audio_path": d["sample_audio_path"],
        "times_used": d["times_used"],
        "added_at": d["added_at"],
        "updated_at": d["updated_at"],
        "voicebox_engine": _row_get(d, "voicebox_engine", "qwen3-tts"),
        "voicebox_effect_preset_id": _row_get(d, "voicebox_effect_preset_id", None),
    }


def _row_get(row: dict[str, Any], key: str, default: Any) -> Any:
    """Like dict.get but tolerates ``sqlite3.Row``-style mappings."""
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return value if value is not None else default


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def list_voices(
    *,
    pool: Optional[str] = None,
    gender: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all voices matching the filters, ordered by pool then display_name.

    `q` searches across display_name, accent, tone_json, tags_json, and
    character_archetypes_json (per adjustment D).
    """
    where: list[str] = []
    params: list[Any] = []

    if pool:
        where.append("pool = ?")
        params.append(pool)
    if gender:
        where.append("gender = ?")
        params.append(gender)
    if q:
        like = f"%{q.lower()}%"
        where.append(
            "("
            "LOWER(display_name) LIKE ? OR "
            "LOWER(COALESCE(accent,'')) LIKE ? OR "
            "LOWER(tone_json) LIKE ? OR "
            "LOWER(tags_json) LIKE ? OR "
            "LOWER(character_archetypes_json) LIKE ?"
            ")"
        )
        params.extend([like] * 5)

    sql = "SELECT * FROM voices"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY pool, LOWER(display_name)"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_voice(r) for r in rows]


def get_voice(voice_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM voices WHERE id = ?", (voice_id,)
        ).fetchone()
    return _row_to_voice(row) if row else None


def count_by_pool() -> dict[str, int]:
    """Return {'narrator': N, 'main': N, 'background': N}. Zeroes included."""
    counts = {"narrator": 0, "main": 0, "background": 0}
    with connect() as conn:
        for row in conn.execute(
            "SELECT pool, COUNT(*) AS c FROM voices GROUP BY pool"
        ):
            counts[row["pool"]] = row["c"]
    return counts


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def create_voice(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a new voice. `data` is the POST payload; audio file handling
    (saving to disk, setting sample_audio_path) happens in the API layer.
    """
    voice_id = data.get("id") or _new_voice_id(data["display_name"])

    columns = [
        "id", "voicebox_profile_id", "display_name", "gender", "age_range",
        "accent", "tone_json", "timbre", "pace", "register",
        "character_archetypes_json", "pool", "engine_preference", "sample_text",
        "source_notes", "tags_json", "sample_audio_path",
        "voicebox_engine", "voicebox_effect_preset_id",
    ]
    values = [
        voice_id,
        data.get("voicebox_profile_id"),  # still NULL at DB insert; eager sync happens in the API layer
        data["display_name"],
        data.get("gender"),
        data.get("age_range"),
        data.get("accent"),
        _dumps(data.get("tone")),
        data.get("timbre"),
        data.get("pace"),
        data.get("register"),
        _dumps(data.get("character_archetypes")),
        data["pool"],
        data.get("engine_preference"),
        data.get("sample_text"),
        data.get("source_notes"),
        _dumps(data.get("tags")),
        data.get("sample_audio_path"),
        data.get("voicebox_engine") or "qwen3-tts",
        data.get("voicebox_effect_preset_id"),
    ]
    placeholders = ", ".join(["?"] * len(columns))

    with connect() as conn:
        conn.execute(
            f"INSERT INTO voices ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
    return _row_to_voice(row)


# Fields that map 1:1 from PATCH payload to SQL columns.
_SCALAR_UPDATE_FIELDS = {
    "display_name", "gender", "age_range", "accent", "timbre", "pace",
    "register", "pool", "engine_preference", "sample_text", "source_notes",
    "voicebox_profile_id",
    # Phase-5 remediation: per-voice engine + effect preset are editable.
    "voicebox_engine", "voicebox_effect_preset_id",
}
# Fields that live in *_json columns.
_ARRAY_UPDATE_FIELDS = {
    "tone": "tone_json",
    "character_archetypes": "character_archetypes_json",
    "tags": "tags_json",
}


def update_voice(voice_id: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Partial update. Only fields present in `data` are written.

    Returns None if the voice doesn't exist.
    """
    sets: list[str] = []
    params: list[Any] = []

    for field in _SCALAR_UPDATE_FIELDS:
        if field in data:
            sets.append(f"{field} = ?")
            params.append(data[field])

    for field, column in _ARRAY_UPDATE_FIELDS.items():
        if field in data:
            sets.append(f"{column} = ?")
            params.append(_dumps(data[field]))

    if "sample_audio_path" in data:
        sets.append("sample_audio_path = ?")
        params.append(data["sample_audio_path"])

    if not sets:
        return get_voice(voice_id)

    sets.append("updated_at = datetime('now')")
    params.append(voice_id)

    with connect() as conn:
        cur = conn.execute(
            f"UPDATE voices SET {', '.join(sets)} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
    return _row_to_voice(row)


def delete_voice(voice_id: str) -> bool:
    """Delete the voice and its reference-audio file. Returns True if deleted."""
    voice = get_voice(voice_id)
    if voice is None:
        return False
    with connect() as conn:
        conn.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
    sample = voice.get("sample_audio_path")
    if sample:
        _safe_unlink(Path(sample))
    return True


def increment_times_used(voice_id: str, *, delta: int = 1) -> None:
    """Bump the usage counter — wire this up later from the audio generator."""
    with connect() as conn:
        conn.execute(
            "UPDATE voices SET times_used = times_used + ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (delta, voice_id),
        )


# ---------------------------------------------------------------------------
# Sample audio file helpers
# ---------------------------------------------------------------------------


def samples_dir() -> Path:
    settings = get_settings()
    settings.voice_samples_path.mkdir(parents=True, exist_ok=True)
    return settings.voice_samples_path


def sample_path_for(voice_id: str, ext: str) -> Path:
    """Deterministic on-disk path for a voice's reference audio.

    ext should include or omit the leading dot — we normalize.
    """
    ext = ext.lower().lstrip(".")
    return samples_dir() / f"{voice_id}.{ext}"


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Don't let a stuck file stop a DB delete; log at caller if important.
        pass


# ---------------------------------------------------------------------------
# voice_samples helpers (Phase 5 remediation Commit 5)
# ---------------------------------------------------------------------------


def add_voice_sample(
    voice_id: str,
    sample_path: str,
    *,
    label: str = "Original",
    voicebox_sample_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Insert (or upsert) a row in ``voice_samples`` for this voice.

    ``(voice_id, sample_path)`` is UNIQUE; repeated calls with the same pair
    update ``voicebox_sample_id`` in place rather than erroring.
    """
    sid = str(uuid.uuid4())
    with connect() as conn:
        # Try INSERT; on UNIQUE conflict, UPDATE the voicebox_sample_id.
        existing = conn.execute(
            "SELECT id FROM voice_samples WHERE voice_id = ? AND sample_path = ?",
            (voice_id, sample_path),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE voice_samples SET voicebox_sample_id = COALESCE(?, voicebox_sample_id), "
                "label = COALESCE(?, label), duration_ms = COALESCE(?, duration_ms) "
                "WHERE id = ?",
                (voicebox_sample_id, label, duration_ms, existing["id"]),
            )
            row_id = existing["id"]
        else:
            conn.execute(
                "INSERT INTO voice_samples "
                "(id, voice_id, sample_path, voicebox_sample_id, label, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, voice_id, sample_path, voicebox_sample_id, label, duration_ms),
            )
            row_id = sid
        row = conn.execute(
            "SELECT * FROM voice_samples WHERE id = ?", (row_id,)
        ).fetchone()
    return dict(row) if row else {}


def list_voice_samples(voice_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_samples WHERE voice_id = ? ORDER BY created_at",
            (voice_id,),
        ).fetchall()
    return [dict(r) for r in rows]
