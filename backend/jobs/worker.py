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
from typing import Any, Awaitable, Callable, Literal, Optional

from backend.jobs import repo
from backend.nlp import file_drop

log = logging.getLogger(__name__)

# Tightened from 2.0s → 1.0s in Phase 4 (§1B): reduces end-to-end latency
# between Claude Code dropping a response and the UI seeing the completed job.
# Don't go below 1s without profiling — the tick holds a DB connection and
# enumerates every awaiting_response job per pass.
POLL_INTERVAL_S = 1.0

# Handler signature: (job_dict, parsed_response_json) -> None. May raise.
Handler = Callable[[dict[str, Any], Any], Awaitable[None]]

# Dispatch modes:
#   - "file_drop": Phase-3/4 pattern. Job sits in awaiting_response; worker
#     polls data/llm_queue/responses/ for the companion session's JSON reply,
#     then invokes handler(job, parsed_payload).
#   - "direct":    Phase-5 pattern. Job sits in queued; worker picks it up on
#     the next tick, transitions it to running, and invokes
#     handler(job, job['payload']) without waiting for any external file.
HandlerMode = Literal["file_drop", "direct"]

_HANDLERS: dict[str, Handler] = {}
_HANDLER_MODES: dict[str, HandlerMode] = {}

# Per-job locks so a single kind that takes multiple ticks (e.g. a long
# generate_segment) isn't re-dispatched on every tick.
_IN_FLIGHT: set[str] = set()


def register_handler(
    kind: str, *, mode: HandlerMode = "file_drop"
) -> Callable[[Handler], Handler]:
    """Decorator that binds a handler to a job ``kind``.

    ``mode`` selects the dispatch pipeline:
      * ``"file_drop"`` (default; Phase 3/4 NLP handlers) — worker waits for
        a ``response_<job_id>.json`` file and invokes the handler with the
        parsed JSON.
      * ``"direct"`` (Phase 5 TTS handlers) — worker picks the job up from the
        ``queued`` queue and invokes the handler with the row's own
        ``payload`` dict.
    """

    def _register(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        _HANDLER_MODES[kind] = mode
        log.debug("registered %s handler for kind=%s", mode, kind)
        return fn

    return _register


def registered_kinds() -> list[str]:
    return sorted(_HANDLERS.keys())


def _direct_kinds() -> list[str]:
    return [k for k, m in _HANDLER_MODES.items() if m == "direct"]


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


async def _process_direct(job: dict[str, Any]) -> None:
    """Run a direct-mode (non-file-drop) handler.

    Payload comes from the job row itself, not from a response file. The
    handler is responsible for moving the job to ``complete`` / ``failed``;
    the worker only marks it ``running`` on pickup and catches exceptions.
    """
    job_id = job["id"]
    kind = job["kind"]
    handler = _HANDLERS.get(kind)
    if handler is None:
        msg = f"no direct handler registered for job kind {kind!r}"
        log.error("%s (job=%s)", msg, job_id)
        repo.set_status(job_id, "failed", error=msg)
        return

    # Move to running so the UI sees progress immediately.
    repo.set_status(job_id, "running", message=f"starting {kind}")

    try:
        await handler(job, job.get("payload"))
    except Exception as e:  # noqa: BLE001 — surface any handler failure
        log.exception("job %s (%s) direct handler failed", job_id, kind)
        repo.set_status(job_id, "failed", error=f"{type(e).__name__}: {e}")
        return

    # Handlers typically call repo.set_status(..., "complete", result=...)
    # themselves (so they can attach per-job result payloads). If a handler
    # forgot, leave the job in ``running`` — this is a bug surface rather
    # than something we should silently paper over.


async def _tick() -> None:
    # --- file-drop flow: jobs parked in awaiting_response -----------------
    awaiting = repo.list_awaiting()
    # Process sequentially — handlers are typically DB-write-bound and this
    # keeps transaction semantics simple. Parallelism isn't needed until
    # attribution in Phase 4+.
    for job in awaiting:
        await _process_one(job)

    # --- direct-dispatch flow: queued jobs for registered direct kinds ----
    direct_kinds = _direct_kinds()
    if not direct_kinds:
        return
    queued = repo.list_jobs(kinds=direct_kinds, statuses=["queued"], limit=1000)
    for job in queued:
        if job["id"] in _IN_FLIGHT:
            continue
        _IN_FLIGHT.add(job["id"])
        try:
            await _process_direct(job)
        finally:
            _IN_FLIGHT.discard(job["id"])


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
