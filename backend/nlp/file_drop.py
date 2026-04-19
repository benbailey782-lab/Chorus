"""File-drop LLM integration (§12A).

Write a rendered prompt to ``data/llm_queue/pending/request_<id>.md``, wait
for ``data/llm_queue/responses/response_<id>.json`` to appear, then move the
request file to ``data/llm_queue/completed/``.

The companion Claude Code session handles actually executing the prompt and
dropping the response; see ``docs/FILE-DROP-WORKFLOW.md`` for the operator
instructions.

All filesystem operations are wrapped in ``asyncio.to_thread`` so they don't
block the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from backend.config import get_settings

log = logging.getLogger(__name__)


class FileDropError(RuntimeError):
    """Base class for file-drop failures."""


class FileDropResponseInvalid(FileDropError):
    """Raised when a response file exists but isn't valid JSON."""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def pending_path(request_id: str) -> Path:
    return get_settings().llm_queue_pending_path / f"request_{request_id}.md"


def response_path(request_id: str) -> Path:
    return get_settings().llm_queue_responses_path / f"response_{request_id}.json"


def completed_path(request_id: str) -> Path:
    return get_settings().llm_queue_completed_path / f"request_{request_id}.md"


# ---------------------------------------------------------------------------
# Request rendering
# ---------------------------------------------------------------------------


def _format_front_matter(metadata: Mapping[str, Any]) -> str:
    """Emit a YAML-ish front-matter block the companion session can eyeball.

    We keep it dependency-free (no yaml lib) by hand-rolling a small subset —
    scalars only, no nested structures. Callers should pass flat string/int
    values.
    """
    lines = ["---"]
    for key in sorted(metadata.keys()):
        raw = metadata[key]
        if raw is None:
            continue
        value = str(raw).replace("\n", " ")
        # Quote strings containing risky chars so they survive a human eyeball.
        if any(c in value for c in ":#\""):
            value = '"' + value.replace('"', '\\"') + '"'
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _render_request_file(
    request_id: str,
    prompt_text: str,
    metadata: Optional[Mapping[str, Any]],
) -> str:
    """Build the full on-disk request_<id>.md contents."""
    fm_dict: dict[str, Any] = {
        "id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if metadata:
        fm_dict.update(metadata)
    fm = _format_front_matter(fm_dict)
    return f"{fm}\n\n{prompt_text.rstrip()}\n"


def _write_request_sync(
    request_id: str,
    prompt_text: str,
    metadata: Optional[Mapping[str, Any]],
) -> Path:
    path = pending_path(request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_request_file(request_id, prompt_text, metadata),
        encoding="utf-8",
    )
    return path


async def submit_request(
    request_id: str,
    prompt_text: str,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Write ``request_<id>.md`` to ``pending/``. Returns the written path."""
    return await asyncio.to_thread(
        _write_request_sync, request_id, prompt_text, metadata
    )


# ---------------------------------------------------------------------------
# Response polling
# ---------------------------------------------------------------------------


def _read_response_sync(request_id: str) -> Optional[Any]:
    path = response_path(request_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise FileDropResponseInvalid(
            f"response_{request_id}.json is not valid JSON: {e}"
        ) from e
    except OSError as e:
        raise FileDropError(f"failed to read {path}: {e}") from e


async def poll_for_response(request_id: str) -> Optional[Any]:
    """Return the parsed JSON if ``response_<id>.json`` exists, else None.

    Raises :class:`FileDropResponseInvalid` if the file exists but doesn't
    parse — callers should surface this as a job error so the operator can
    fix and re-drop.
    """
    return await asyncio.to_thread(_read_response_sync, request_id)


# ---------------------------------------------------------------------------
# Completion + cleanup
# ---------------------------------------------------------------------------


def _mark_completed_sync(request_id: str) -> None:
    src = pending_path(request_id)
    dst = completed_path(request_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        # Prefer atomic rename when on the same filesystem.
        try:
            src.replace(dst)
        except OSError as e:
            raise FileDropError(f"failed to move {src} → {dst}: {e}") from e
    # If src doesn't exist, treat as already-completed — idempotent no-op.


async def mark_completed(request_id: str) -> None:
    """Atomically move ``pending/request_<id>.md`` → ``completed/``.

    Idempotent: calling twice for the same id is a no-op the second time.
    """
    await asyncio.to_thread(_mark_completed_sync, request_id)


def _delete_response_sync(request_id: str) -> None:
    path = response_path(request_id)
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("failed to delete response file %s: %s", path, e)


async def delete_response(request_id: str) -> None:
    """Remove the response file once Chorus has persisted its contents."""
    await asyncio.to_thread(_delete_response_sync, request_id)


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def _scan_sync() -> dict[str, list[str]]:
    s = get_settings()
    return {
        "pending": sorted(p.stem for p in s.llm_queue_pending_path.glob("request_*.md")),
        "responses": sorted(p.stem for p in s.llm_queue_responses_path.glob("response_*.json")),
        "completed": sorted(p.stem for p in s.llm_queue_completed_path.glob("request_*.md")),
    }


async def scan_queue() -> dict[str, list[str]]:
    """Return a snapshot of queue contents for health/debug views."""
    return await asyncio.to_thread(_scan_sync)
