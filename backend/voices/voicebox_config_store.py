"""Runtime-writable Voicebox config (Phase 5 remediation).

Voicebox v0.4.0 picks a runtime port on launch, so the operator can't know
the URL until Voicebox prints it. We need the Settings UI to be able to
save + reload the URL without a backend restart.

Strategy
--------
Pydantic's :class:`backend.config.Settings` is ``@lru_cache``'d (env is
immutable for a process lifetime) — we don't want to bust that cache every
time the user saves. Instead, Voicebox-specific reads go through
``get_effective()`` here on every request, which:

  1. Reads ``data/voicebox_config.json`` if present + non-empty.
  2. Falls back to ``settings.voicebox_base_url`` / ``voicebox_enabled``.

That means the voicebox client + ``/api/voicebox/status`` + any future
per-request reader that cares about a live URL will pick up UI-saved
changes immediately without a process restart, while all the other
Settings fields stay cached-for-lifetime as before.

File shape
----------
::

    {"base_url": "http://localhost:17493", "enabled": true}

Missing file / malformed JSON → treated as "no override" and we fall back
to env defaults. Write is atomic-enough for a single-user local app:
write to ``<path>.tmp`` then ``os.replace``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

_CONFIG_FILENAME = "voicebox_config.json"


def _config_path(settings: Optional[Settings] = None) -> Path:
    s = settings or get_settings()
    return s.data_path / _CONFIG_FILENAME


def load(settings: Optional[Settings] = None) -> dict[str, Any]:
    """Return the raw file contents, or an empty dict if missing/invalid."""
    path = _config_path(settings)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        log.warning("voicebox_config.json unreadable (%s) — ignoring", e)
        return {}
    if not isinstance(data, dict):
        log.warning("voicebox_config.json is not an object — ignoring")
        return {}
    return data


def save(base_url: str, enabled: bool, settings: Optional[Settings] = None) -> None:
    """Persist ``{base_url, enabled}`` to ``data/voicebox_config.json``.

    ``base_url`` is stripped; the empty string is valid and means
    "unconfigured" (the UI uses this to clear a saved URL).
    """
    s = settings or get_settings()
    # ensure_dirs() already runs at Settings() construction via get_settings,
    # but we guard here in case the data dir got nuked between startup and
    # the first save.
    s.data_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": (base_url or "").strip(),
        "enabled": bool(enabled),
    }
    path = _config_path(s)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def get_effective(settings: Optional[Settings] = None) -> tuple[str, bool]:
    """Return ``(base_url, enabled)`` with file-first, env-fallback resolution.

    Rules:
      * If the file exists with a non-empty ``base_url`` → use the file's
        ``base_url`` + ``enabled``.
      * Else if the env provides a ``base_url`` → use env for both fields.
      * Else → ``("", False)``.

    Strings are stripped. Booleans are coerced via ``bool()`` so JSON's
    ``true``/``false`` and ints both round-trip correctly.
    """
    s = settings or get_settings()
    data = load(s)
    file_url = str(data.get("base_url") or "").strip()
    if file_url:
        return file_url, bool(data.get("enabled", False))
    env_url = (s.voicebox_base_url or "").strip()
    if env_url:
        return env_url, bool(s.voicebox_enabled)
    return "", False
