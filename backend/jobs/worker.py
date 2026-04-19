"""Background worker that reconciles file-drop responses with awaiting jobs.

Every ``POLL_INTERVAL_S`` seconds, scans ``data/llm_queue/responses/`` for
``response_<id>.json`` files matching a job in ``awaiting_response``. For each
hit, dispatches the parsed payload to the handler registered for that job's
``kind`` and advances the job.

Handlers live in ``backend/nlp/*.py`` and register themselves via
:func:`register_handler`. Each handler is ``async def handle(job, payload)``
and is expected to raise on validation failure (the worker catches and marks
the job failed with the exception message).

The file-drop module (§12A) is the only LLM transport in v1 — there is
deliberately no Anthropic SDK code path here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from backend.jobs import repo
from backend.nlp import file_drop

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0

# Handler signature: (job_dict, parsed_response_json) -> None. May raise.
Handler = Callable[[dict[str, Any], Any], Awaitable[None]]

_HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str) -> Callable[[Handler], Handler]:
    """Decorator that binds a handler to a job ``kind``."""

    def _register(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        log.debug("registered file-drop handler for kind=%s", kind)
        return fn

    return _register


def registered_kinds() -> list[str]:
    return sorted(_HANDLERS.keys())


async def _process_one(job: dict[str, Any]) -> None:
    job_id = job["id"]
    kind = job["kind"]
    handler = _HANDLERS.get(kind)
    if handler is None:
        # Unknown kind — surface clearly and stop trying. A future worker
        # iteration will skip it because the job moves out of
        # awaiting_response.
        msg = (
            f"no handler registered for job kind {kind!r} — "
            "file-drop response cannot be ingested"
        )
        log.error("%s (job=%s)", msg, job_id)
        repo.set_status(job_id, "failed", error=msg)
        return

    try:
        payload = await file_drop.poll_for_response(job_id)
    except file_drop.FileDropResponseInvalid as e:
        log.warning("job %s: invalid response JSON — %s", job_id, e)
        repo.set_status(job_id, "failed", error=str(e))
        return

    if payload is None:
        # Response not here yet.
        return

    try:
        await handler(job, payload)
    except Exception as e:  # noqa: BLE001 — surface any handler failure
        log.exception("job %s (%s) handler failed", job_id, kind)
        repo.set_status(job_id, "failed", error=f"{type(e).__name__}: {e}")
        # Leave the request file in pending/ and the response in responses/
        # so the operator can inspect, fix, and re-drop.
        return

    # Handler was responsible for marking the job `complete`. Clean up the
    # file-drop queue artifacts regardless.
    try:
        await file_drop.mark_completed(job_id)
    except Exception:  # noqa: BLE001
        log.exception("failed to move request_%s.md to completed/", job_id)
    try:
        await file_drop.delete_response(job_id)
    except Exception:  # noqa: BLE001
        log.exception("failed to delete response_%s.json", job_id)


async def _tick() -> None:
    awaiting = repo.list_awaiting()
    if not awaiting:
        return
    # Process sequentially — handlers are typically DB-write-bound and this
    # keeps transaction semantics simple. Parallelism isn't needed until
    # attribution in Phase 4+.
    for job in awaiting:
        await _process_one(job)


async def run_forever(stop_event: asyncio.Event) -> None:
    """Run until ``stop_event`` is set. Intended to be launched as a task
    from the FastAPI lifespan context."""
    log.info("file-drop worker starting (poll interval: %.1fs)", POLL_INTERVAL_S)
    while not stop_event.is_set():
        try:
            await _tick()
        except Exception:  # noqa: BLE001 — never let the loop die
            log.exception("file-drop worker tick errored")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
    log.info("file-drop worker stopped")


# ---------------------------------------------------------------------------
# Lifespan integration helpers
# ---------------------------------------------------------------------------


class WorkerHandle:
    """Small container returned from :func:`start` — call ``.stop()`` to shut down."""

    def __init__(self, task: asyncio.Task[None], stop_event: asyncio.Event):
        self._task = task
        self._stop_event = stop_event

    async def stop(self) -> None:
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=POLL_INTERVAL_S + 1.0)
        except asyncio.TimeoutError:
            self._task.cancel()


def start() -> WorkerHandle:
    """Launch the worker as a background task. Must be called from inside
    an active event loop (e.g., FastAPI lifespan)."""
    # Importing handlers here ensures they register before the loop starts.
    # (The actual handlers live in backend/nlp/extract_characters.py and
    # backend/nlp/auto_cast.py — both imported by the lifespan setup.)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    task = loop.create_task(run_forever(stop_event), name="chorus-file-drop-worker")
    return WorkerHandle(task, stop_event)
