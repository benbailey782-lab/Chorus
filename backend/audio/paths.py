"""Central path helpers for per-segment audio files (Phase 5).

Layout (§6 clarification):

    data/projects/<project_id>/audio/raw/<chapter_id>/segment_<segment_id>.<ext>
    data/projects/<project_id>/audio/approved/<chapter_id>/segment_<segment_id>.<ext>

The only side effect in this module is ``mkdir(..., parents=True,
exist_ok=True)`` from the directory helpers; pure path builders (e.g.
:func:`raw_segment_path`) never touch the filesystem.
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)


def project_audio_dir(project_id: str) -> Path:
    """Return ``data/projects/<project_id>/audio`` (creates if missing)."""
    p = get_settings().projects_path / project_id / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_dir(project_id: str, chapter_id: str) -> Path:
    """Return the raw-audio directory for a chapter, creating it if missing."""
    p = project_audio_dir(project_id) / "raw" / chapter_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def approved_dir(project_id: str, chapter_id: str) -> Path:
    """Return the approved-audio directory for a chapter, creating it if missing."""
    p = project_audio_dir(project_id) / "approved" / chapter_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_segment_glob(project_id: str, chapter_id: str, segment_id: str) -> list[Path]:
    """Existing files matching ``segment_<segment_id>.*`` in the raw dir.

    Pure lookup — does not create the directory. Returns ``[]`` if the dir
    doesn't exist.
    """
    base = get_settings().projects_path / project_id / "audio" / "raw" / chapter_id
    if not base.exists():
        return []
    pattern = str(base / f"segment_{segment_id}.*")
    return [Path(p) for p in glob.glob(pattern)]


def approved_segment_glob(project_id: str, chapter_id: str, segment_id: str) -> list[Path]:
    """Existing approved files matching ``segment_<segment_id>.*``. Pure lookup."""
    base = get_settings().projects_path / project_id / "audio" / "approved" / chapter_id
    if not base.exists():
        return []
    pattern = str(base / f"segment_{segment_id}.*")
    return [Path(p) for p in glob.glob(pattern)]


def raw_segment_path(
    project_id: str, chapter_id: str, segment_id: str, ext: str
) -> Path:
    """Build the full raw-audio path for a segment. Creates parent dirs."""
    return raw_dir(project_id, chapter_id) / f"segment_{segment_id}.{ext.lstrip('.')}"


def approved_segment_path(
    project_id: str, chapter_id: str, segment_id: str, ext: str
) -> Path:
    """Build the full approved-audio path for a segment. Creates parent dirs."""
    return approved_dir(project_id, chapter_id) / f"segment_{segment_id}.{ext.lstrip('.')}"


# ---------------------------------------------------------------------------
# MIME → extension
# ---------------------------------------------------------------------------

_CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
}


def ext_from_content_type(content_type: str | None) -> str:
    """Map an HTTP ``Content-Type`` to a file extension (no leading dot).

    - ``audio/wav`` → ``"wav"``
    - ``audio/mpeg`` → ``"mp3"``
    - ``audio/mp4`` → ``"m4a"``
    - Unknown / ``None`` → ``"wav"`` (with a caller-visible warning log).
    """
    if not content_type:
        log.warning("ext_from_content_type: empty/None content_type; defaulting to wav")
        return "wav"
    # Strip parameters like "; charset=..."
    main = content_type.split(";", 1)[0].strip().lower()
    ext = _CONTENT_TYPE_TO_EXT.get(main)
    if ext:
        return ext
    log.warning("ext_from_content_type: unknown content_type %r; defaulting to wav", content_type)
    return "wav"


# ---------------------------------------------------------------------------
# Content-Type lookup by extension (for streaming endpoints)
# ---------------------------------------------------------------------------

_EXT_TO_CONTENT_TYPE: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
}


def content_type_from_ext(ext: str) -> str:
    """Reverse mapping for stream responses. Unknown → ``application/octet-stream``."""
    return _EXT_TO_CONTENT_TYPE.get(ext.lstrip(".").lower(), "application/octet-stream")
