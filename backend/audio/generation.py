"""TTS orchestration + ``generate_segment`` job handler (Phase 5, §10.5).

Single source of truth for:
  * per-segment and per-chapter duration estimates (§10.5 default 2.5 wps),
  * pronunciation substitution using the project-scoped merged map,
  * voice resolution (segment override → character voice → narrator pool),
  * the actual Voicebox call (wrapped in a concurrency semaphore so the
    Phase-5 default of 1-at-a-time can be bumped later without code changes),
  * the ``generate_segment`` handler (direct-mode; not file-drop),
  * chapter- and segment-level trigger entry points used by the API layer.

Design notes:
  * Functions that take a ``conn`` kwarg accept an optional pre-opened SQLite
    connection so the API can batch many reads inside a single transaction.
    When omitted each helper opens its own ``connect()`` context.
  * ``resolve_voice_for_segment`` raises :class:`NoVoiceResolvedError` when
    nothing resolves — by spec the narrator pool should always have at least
    one voice before attribution, but the handler still has to defend
    against empty pools (§7.4).
  * ``apply_pronunciations`` uses a case-insensitive word-boundary match and
    returns the substituted text verbatim (no case preservation on the
    replacement — the phonetic respelling *is* the canonical form Voicebox
    should see). ``changed?`` flips to True on any substitution.
  * Text for generation = segment.text (post-user-edits) → pronunciation
    substitution. Voicebox gets the final string exactly as stored in
    ``segment.text`` apart from pronunciation swaps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from backend.audio import paths as audio_paths
from backend.config import get_settings
from backend.db import connect
from backend.jobs import repo, worker
from backend.nlp.merge_pronunciations import MergedEntry, merge_pronunciations
from backend.voices import voicebox_client
from backend.voices.voicebox_client import (
    SynthesisOptions,
    SynthesisResult,
    VoiceboxError,
    VoiceboxNotEnabled,
    VoiceboxUnreachableError,
)

log = logging.getLogger(__name__)

JOB_KIND = "generate_segment"

# Segments that are considered "already covered" when computing
# "ungenerated" estimates / chapter-level triggers.
_COVERED_STATUSES = {"generated", "approved"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GenerationError(RuntimeError):
    """Base class for TTS generation orchestration failures."""


class NoVoiceResolvedError(GenerationError):
    """Raised when no voice can be resolved for a segment.

    Priority order (see :func:`resolve_voice_for_segment`):
      segment.voice_override_id → character.voice_id → any narrator-pool voice.
    """


class SegmentNotFoundError(GenerationError):
    """Segment id doesn't exist (or has no parent chapter/project)."""


class VoiceMissingProfileError(GenerationError):
    """Resolved voice has no Voicebox profile_id — TTS can't call out."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class EstimateResult:
    seconds: float
    words: int
    segments: int
    wps_factor: float
    human_label: str


@dataclass
class GenerationResult:
    segment_id: str
    audio_path: str                 # relative to repo root
    duration_ms: Optional[int]
    sample_rate: Optional[int]
    content_type: Optional[str]
    text_modified: bool             # True if pronunciation substitution altered text


@dataclass
class TriggerResult:
    job_id: str
    estimated_seconds: float


@dataclass
class ChapterTriggerResult:
    job_ids: list[str]
    segment_count: int
    total_estimated_seconds: float


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

_sem: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazily initialized because :func:`get_settings` reads env on first call
    and the semaphore must be bound to the running loop."""
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(get_settings().voicebox_max_concurrent_generations)
    return _sem


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def _human_label(seconds: float) -> str:
    if seconds < 60:
        return f"{int(round(seconds))} s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"~{int(round(minutes))} min"
    hours = minutes / 60.0
    return f"~{hours:.1f} hr"


def _seconds_from_words(words: int, wps: float) -> float:
    if wps <= 0:
        return 0.0
    return words / wps


def estimate_segment_duration(
    segment_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> EstimateResult:
    """Seconds-based duration estimate for a single segment.

    Uses ``settings.voicebox_default_wps`` as the words-per-second factor.
    """
    wps = float(get_settings().voicebox_default_wps)

    def _do(c: sqlite3.Connection) -> EstimateResult:
        row = c.execute(
            "SELECT text FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        if not row:
            raise SegmentNotFoundError(f"segment {segment_id!r} not found")
        words = _word_count(row["text"])
        seconds = _seconds_from_words(words, wps)
        return EstimateResult(
            seconds=seconds,
            words=words,
            segments=1,
            wps_factor=wps,
            human_label=_human_label(seconds),
        )

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


def estimate_chapter_duration(
    chapter_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> EstimateResult:
    """Seconds-based duration estimate for every segment in a chapter."""
    wps = float(get_settings().voicebox_default_wps)

    def _do(c: sqlite3.Connection) -> EstimateResult:
        rows = c.execute(
            "SELECT text FROM segments WHERE chapter_id = ?", (chapter_id,)
        ).fetchall()
        words = sum(_word_count(r["text"]) for r in rows)
        seconds = _seconds_from_words(words, wps)
        return EstimateResult(
            seconds=seconds,
            words=words,
            segments=len(rows),
            wps_factor=wps,
            human_label=_human_label(seconds),
        )

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


def estimate_chapter_ungenerated(
    chapter_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> EstimateResult:
    """Estimate for only the segments without audio yet.

    "Without audio" = ``audio_path IS NULL`` OR ``status NOT IN
    ('generated', 'approved')``. Matches what :func:`trigger_chapter` would
    actually generate.
    """
    wps = float(get_settings().voicebox_default_wps)

    def _do(c: sqlite3.Connection) -> EstimateResult:
        rows = c.execute(
            """
            SELECT text FROM segments
            WHERE chapter_id = ?
              AND (audio_path IS NULL OR status NOT IN ('generated','approved'))
            """,
            (chapter_id,),
        ).fetchall()
        words = sum(_word_count(r["text"]) for r in rows)
        seconds = _seconds_from_words(words, wps)
        return EstimateResult(
            seconds=seconds,
            words=words,
            segments=len(rows),
            wps_factor=wps,
            human_label=_human_label(seconds),
        )

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


# ---------------------------------------------------------------------------
# Pronunciation substitution
# ---------------------------------------------------------------------------


def apply_pronunciations(
    text: str, merged: dict[str, MergedEntry]
) -> tuple[str, bool]:
    """Replace every ``term`` in ``text`` with its ``phonetic`` respelling.

    * Case-insensitive match with word boundaries (``\\b`` on both sides).
    * The *replacement* is the stored phonetic exactly as-is — we don't try to
      case-preserve. The phonetic *is* the canonical form Voicebox should
      pronounce, so "Tyrion" → "TEER-ee-on" (not "Teer-ee-on") even if the
      matched occurrence was sentence-initial.
    * Longest-term-first ordering so "Lord Varys" fires before "Varys".
    * Returns ``(new_text, changed?)``. ``changed?`` is True iff at least one
      substitution applied.
    """
    if not text or not merged:
        return text, False

    # Sort longest first so multi-word terms match before single-word ones.
    terms = sorted(
        ((e.term, e.phonetic) for e in merged.values() if e.term and e.phonetic),
        key=lambda t: len(t[0]),
        reverse=True,
    )
    if not terms:
        return text, False

    changed = False
    out = text
    for term, phonetic in terms:
        # re.escape guards against regex metacharacters inside terms
        # (e.g. "Jon's" — apostrophe is literal, but better safe).
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        new_out, n = pattern.subn(phonetic, out)
        if n > 0:
            changed = True
            out = new_out
    return out, changed


# ---------------------------------------------------------------------------
# Voice resolution
# ---------------------------------------------------------------------------


async def resolve_voice_for_segment(
    segment_row: sqlite3.Row, *, conn: sqlite3.Connection
) -> str:
    """Return the Voicebox ``profile_id`` to use for this segment.

    Priority:
      1. ``segments.voice_override_id``
      2. ``characters.voice_id`` (where characters.id = segments.character_id)
      3. Any voice in the narrator pool (lowest id for determinism).

    Raises:
      * :class:`NoVoiceResolvedError` — nothing at all resolves.
      * :class:`VoiceMissingProfileError` — a voice resolves but has no
        ``voicebox_profile_id`` (Chorus voice was never registered with
        Voicebox; see §7.4).
    """

    def _voice_profile(voice_id: str) -> tuple[Optional[str], Optional[str]]:
        row = conn.execute(
            "SELECT id, voicebox_profile_id FROM voices WHERE id = ?", (voice_id,)
        ).fetchone()
        if not row:
            return None, None
        return row["id"], row["voicebox_profile_id"]

    # (1) Segment-level override.
    override_id = segment_row["voice_override_id"] if "voice_override_id" in segment_row.keys() else None
    if override_id:
        vid, profile = _voice_profile(override_id)
        if vid is not None:
            if not profile:
                raise VoiceMissingProfileError(
                    f"segment voice override {vid!r} has no voicebox_profile_id"
                )
            return profile
        log.warning(
            "segment %s: voice_override_id=%r not found in voices table; falling through",
            segment_row["id"], override_id,
        )

    # (2) Character assignment.
    char_id = segment_row["character_id"] if "character_id" in segment_row.keys() else None
    if char_id:
        char_row = conn.execute(
            "SELECT voice_id FROM characters WHERE id = ?", (char_id,)
        ).fetchone()
        if char_row and char_row["voice_id"]:
            vid, profile = _voice_profile(char_row["voice_id"])
            if vid is not None:
                if not profile:
                    raise VoiceMissingProfileError(
                        f"character voice {vid!r} has no voicebox_profile_id"
                    )
                return profile
            log.warning(
                "segment %s: character %s has voice_id=%r but voice row missing",
                segment_row["id"], char_id, char_row["voice_id"],
            )

    # (3) Narrator fallback.
    narrator = conn.execute(
        "SELECT id, voicebox_profile_id FROM voices WHERE pool = 'narrator' "
        "ORDER BY id LIMIT 1"
    ).fetchone()
    if narrator is None:
        raise NoVoiceResolvedError(
            "no voice resolved for segment: segment has no override, character has no voice, "
            "and the narrator pool is empty. Add at least one narrator voice via /voices."
        )
    if not narrator["voicebox_profile_id"]:
        raise VoiceMissingProfileError(
            f"narrator fallback voice {narrator['id']!r} has no voicebox_profile_id "
            "(not registered with Voicebox)"
        )
    return narrator["voicebox_profile_id"]


# ---------------------------------------------------------------------------
# Project / chapter / segment lookups
# ---------------------------------------------------------------------------


def _load_segment_context(
    segment_id: str, conn: sqlite3.Connection
) -> tuple[sqlite3.Row, str, str]:
    """Return ``(segment_row, chapter_id, project_id)``. Raises if missing."""
    row = conn.execute(
        """
        SELECT s.*, c.project_id AS project_id, s.chapter_id AS chapter_id_
        FROM segments s JOIN chapters c ON s.chapter_id = c.id
        WHERE s.id = ?
        """,
        (segment_id,),
    ).fetchone()
    if not row:
        raise SegmentNotFoundError(f"segment {segment_id!r} not found")
    return row, row["chapter_id"], row["project_id"]


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------


def _repo_rel_path(abs_path) -> str:
    """Return a repo-root-relative path string for DB storage."""
    from pathlib import Path

    abs_path = Path(abs_path)
    # Path semantics: compute relative to the data_dir's parent (repo root).
    try:
        root = Path(".").resolve()
        return str(abs_path.resolve().relative_to(root))
    except ValueError:
        # Fall back to absolute if we can't relativize (e.g. data on another drive).
        return str(abs_path.resolve())


def _delete_raw_files(project_id: str, chapter_id: str, segment_id: str) -> int:
    """Remove any existing raw files for this segment. Returns count removed."""
    n = 0
    for p in audio_paths.raw_segment_glob(project_id, chapter_id, segment_id):
        try:
            p.unlink()
            n += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("failed to remove raw audio %s: %s", p, e)
    return n


def _delete_approved_files(project_id: str, chapter_id: str, segment_id: str) -> int:
    n = 0
    for p in audio_paths.approved_segment_glob(project_id, chapter_id, segment_id):
        try:
            p.unlink()
            n += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("failed to remove approved audio %s: %s", p, e)
    return n


async def generate_segment(
    segment_id: str, *, force: bool = False
) -> GenerationResult:
    """Generate TTS for a single segment (voice resolution → synthesize → write).

    Lifecycle:
      1. Load segment + chapter + project.
      2. If segment already has audio and ``force=False``, return the existing
         state (no-op).
      3. Transition segment to ``status='generating'``.
      4. Merge pronunciations, apply substitution.
      5. Resolve voice profile.
      6. Call ``voicebox_client.synthesize`` under the concurrency semaphore.
      7. Derive extension from Content-Type, write file.
      8. Update ``segments`` row: ``audio_path``, ``duration_ms``,
         ``status='generated'``. Clears ``approved_at`` when regenerating.
      9. Return :class:`GenerationResult`.

    Raises on Voicebox errors. The caller (usually the direct job handler) is
    responsible for flipping ``segments.status`` to ``'error'`` on exception.
    """
    with connect() as conn:
        seg_row, chapter_id, project_id = _load_segment_context(segment_id, conn)
        existing_path = seg_row["audio_path"]
        existing_status = seg_row["status"]

        if existing_path and not force:
            log.info(
                "generate_segment %s: audio already exists at %s; skipping",
                segment_id, existing_path,
            )
            return GenerationResult(
                segment_id=segment_id,
                audio_path=existing_path,
                duration_ms=seg_row["duration_ms"],
                sample_rate=None,
                content_type=None,
                text_modified=False,
            )

        # Resolve voice first so we fail fast before touching status.
        profile_id = await resolve_voice_for_segment(seg_row, conn=conn)

        # Pronunciation substitution.
        merged = merge_pronunciations(project_id)
        text_for_tts, text_changed = apply_pronunciations(seg_row["text"], merged)

        # Transition to generating.
        conn.execute(
            "UPDATE segments SET status='generating', updated_at=datetime('now') "
            "WHERE id=?",
            (segment_id,),
        )

    # Call Voicebox outside the DB context so we don't hold the connection.
    settings = get_settings()
    options = SynthesisOptions(
        sample_rate=settings.voicebox_output_sample_rate,
    )

    async with _get_semaphore():
        result: SynthesisResult = await voicebox_client.synthesize(
            profile_id, text_for_tts, options=options
        )

    ext = audio_paths.ext_from_content_type(result.content_type)
    # On regenerate, wipe any stale files with different extensions.
    if force:
        _delete_raw_files(project_id, chapter_id, segment_id)
        _delete_approved_files(project_id, chapter_id, segment_id)
    out_path = audio_paths.raw_segment_path(project_id, chapter_id, segment_id, ext)
    out_path.write_bytes(result.audio_bytes)

    rel_path = _repo_rel_path(out_path)

    with connect() as conn:
        # Clear approved_at only on regeneration — a brand-new generation
        # has approved_at already NULL.
        sets = [
            "audio_path = ?",
            "duration_ms = ?",
            "status = 'generated'",
            "updated_at = datetime('now')",
        ]
        params: list[Any] = [rel_path, result.duration_ms]
        if force:
            sets.append("approved_at = NULL")
        conn.execute(
            f"UPDATE segments SET {', '.join(sets)} WHERE id = ?",
            (*params, segment_id),
        )

    return GenerationResult(
        segment_id=segment_id,
        audio_path=rel_path,
        duration_ms=result.duration_ms,
        sample_rate=result.sample_rate,
        content_type=result.content_type,
        text_modified=text_changed,
    )


# ---------------------------------------------------------------------------
# Direct job handler
# ---------------------------------------------------------------------------


@worker.register_handler(JOB_KIND, mode="direct")
async def handle_generate_segment(job: dict[str, Any], payload: Any) -> None:
    """Direct-mode handler for ``generate_segment`` jobs.

    Payload shape (from :func:`trigger_segment`):
        {"segment_id": str, "force": bool}

    On failure the handler flips ``segments.status = 'error'`` and marks the
    job failed. On success the job is marked complete with a result payload
    of ``{segment_id, audio_path, duration_ms, text_modified}``.
    """
    job_id = job["id"]
    if not isinstance(payload, dict):
        raise GenerationError(
            f"generate_segment job {job_id} has invalid payload {payload!r}"
        )
    segment_id = payload.get("segment_id")
    if not segment_id:
        raise GenerationError(
            f"generate_segment job {job_id} payload missing segment_id"
        )
    force = bool(payload.get("force", False))

    try:
        result = await generate_segment(segment_id, force=force)
    except (VoiceboxNotEnabled, VoiceboxUnreachableError, VoiceboxError,
            NoVoiceResolvedError, VoiceMissingProfileError, GenerationError) as e:
        # Segment status → 'error'. Keep existing audio_path / duration_ms so
        # the UI can still let the user inspect the last good generation.
        try:
            with connect() as conn:
                conn.execute(
                    "UPDATE segments SET status='error', updated_at=datetime('now') "
                    "WHERE id = ?",
                    (segment_id,),
                )
        except Exception:  # noqa: BLE001 — writing error state shouldn't mask
            log.exception("failed to flip segment %s to error status", segment_id)
        repo.set_status(
            job_id, "failed", error=f"{type(e).__name__}: {e}",
            message=f"segment {segment_id}: {e}",
        )
        log.warning("generate_segment job %s failed: %s", job_id, e)
        return

    repo.set_status(
        job_id,
        "complete",
        result={
            "segment_id": result.segment_id,
            "audio_path": result.audio_path,
            "duration_ms": result.duration_ms,
            "text_modified": result.text_modified,
        },
        message=f"generated {result.segment_id} ({result.duration_ms}ms)"
        if result.duration_ms is not None
        else f"generated {result.segment_id}",
    )


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


async def trigger_segment(
    segment_id: str, *, force: bool = False
) -> TriggerResult:
    """Enqueue a ``generate_segment`` job for a single segment.

    On a ``regenerate`` call (``force=True``) the raw + approved files and
    ``approved_at`` are wiped *immediately* — the UI treats this as a
    destructive action (the current audio is gone before the new job
    finishes), matching user expectations for "Regenerate".
    """
    with connect() as conn:
        seg_row, chapter_id, project_id = _load_segment_context(segment_id, conn)
        est = estimate_segment_duration(segment_id, conn=conn)

    if force:
        _delete_raw_files(project_id, chapter_id, segment_id)
        _delete_approved_files(project_id, chapter_id, segment_id)
        with connect() as conn:
            conn.execute(
                "UPDATE segments SET audio_path=NULL, duration_ms=NULL, "
                "approved_at=NULL, status='pending', updated_at=datetime('now') "
                "WHERE id=?",
                (segment_id,),
            )

    job = repo.create_job(
        project_id=project_id,
        kind=JOB_KIND,
        payload={"segment_id": segment_id, "force": force},
        status="queued",
        message=(
            f"Regenerate segment {segment_id}" if force
            else f"Generate segment {segment_id}"
        ),
    )
    return TriggerResult(job_id=job["id"], estimated_seconds=est.seconds)


async def trigger_chapter(
    chapter_id: str, *, include_already_generated: bool = False
) -> ChapterTriggerResult:
    """Enqueue one ``generate_segment`` job per target segment in the chapter.

    When ``include_already_generated=False`` (default), skips segments whose
    ``audio_path`` is set and whose status is in ``{generated, approved}``.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
        if not row:
            raise GenerationError(f"chapter {chapter_id!r} not found")
        project_id = row["project_id"]

        if include_already_generated:
            seg_rows = conn.execute(
                "SELECT id, text FROM segments WHERE chapter_id = ? ORDER BY order_index",
                (chapter_id,),
            ).fetchall()
        else:
            seg_rows = conn.execute(
                """
                SELECT id, text FROM segments
                WHERE chapter_id = ?
                  AND (audio_path IS NULL OR status NOT IN ('generated','approved'))
                ORDER BY order_index
                """,
                (chapter_id,),
            ).fetchall()

    wps = float(get_settings().voicebox_default_wps)
    total_seconds = 0.0
    job_ids: list[str] = []
    for seg in seg_rows:
        total_seconds += _seconds_from_words(_word_count(seg["text"]), wps)
        job = repo.create_job(
            project_id=project_id,
            kind=JOB_KIND,
            payload={
                "segment_id": seg["id"],
                "force": bool(include_already_generated),
            },
            status="queued",
            message=f"Generate segment {seg['id']}",
        )
        job_ids.append(job["id"])

    # Flip the project into "generating" if it was still in "attributed"; don't
    # clobber later stages.
    if job_ids:
        with connect() as conn:
            conn.execute(
                "UPDATE projects SET status='generating', updated_at=datetime('now') "
                "WHERE id=? AND status IN ('attributed','casting','attributing')",
                (project_id,),
            )

    return ChapterTriggerResult(
        job_ids=job_ids,
        segment_count=len(job_ids),
        total_estimated_seconds=total_seconds,
    )
