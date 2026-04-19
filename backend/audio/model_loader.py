"""Coordinates Voicebox model loading with in-process cache + progress tracking.

Voicebox v0.4.0 loads large TTS models lazily on first use. Chorus'
generation pipeline calls :func:`ensure_model_loaded` before every
synthesis; the first call for a given engine kicks the model load,
polls progress until complete, and caches the result so subsequent
calls are no-ops. An :class:`asyncio.Lock` per model prevents a
thundering herd when multiple generate jobs start simultaneously.

The cache is in-process only: on backend restart the cache resets,
but Voicebox itself keeps the model loaded server-side, so
:func:`get_model_status` returns ``loaded=True`` on the first probe
after restart and we skip straight to marking it cached.
"""

from __future__ import annotations

import asyncio
import logging

from backend.voices import voicebox_client as vb

log = logging.getLogger(__name__)

# Model names confirmed loaded this process. Keyed by Voicebox model name.
_loaded_models: set[str] = set()

# One lock per model to prevent duplicate POST /models/load during a
# thundering herd. dict access is safe from the single event loop.
_load_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Engine → model mapping
# ---------------------------------------------------------------------------

# Voicebox v0.4.0 model names are partially unverified. Qwen3-TTS is
# confirmed as ``qwen-tts-1.7B`` (per the Voicebox UI labeling). Others
# are best-effort; the operator may need to adjust once the relevant
# models are downloaded and the real Voicebox-side model_name is known.
_ENGINE_TO_MODEL: dict[str, str] = {
    "qwen3-tts": "qwen-tts-1.7B",
    "chatterbox-turbo": "chatterbox-turbo",
    "chatterbox-multilingual": "chatterbox-multilingual",
    "luxtts": "luxtts",
    "humeai-tada": "humeai-tada",
    "kokoro-82m": "kokoro-82m",
    "qwen-custom-voice": "qwen-custom-voice",
}


def model_for_engine(engine: str) -> str:
    """Maps a Chorus engine name → Voicebox model name.

    Raises :class:`KeyError` if the engine is unknown. Callers should
    treat an unknown engine as a config bug, not a runtime surprise —
    ``voices.voicebox_engine`` has a CHECK constraint enforcing the
    same vocabulary (see ``backend/db.py``).
    """
    try:
        return _ENGINE_TO_MODEL[engine]
    except KeyError as e:
        raise KeyError(
            f"unknown voicebox engine {engine!r}. Known engines: "
            f"{sorted(_ENGINE_TO_MODEL)}"
        ) from e


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _now() -> float:
    """Loop-monotonic time — safe inside an async coroutine."""
    return asyncio.get_event_loop().time()


async def ensure_model_loaded(engine: str) -> str:
    """Ensure the Voicebox model for this engine is loaded.

    Returns the Voicebox model name used.

    Behavior:
      1. If already cached as loaded in this process → return immediately.
      2. Otherwise acquire a per-model lock and re-check the cache.
      3. Probe ``GET /models/status`` — if Voicebox already has it
         loaded, mark cached and return.
      4. Otherwise ``POST /models/load`` and poll
         ``GET /models/progress/{name}`` until status is terminal.

    Raises:
      * :class:`voicebox_client.VoiceboxModelNotLoaded` — Voicebox
        reported status=error during load.
      * :class:`voicebox_client.VoiceboxTimeoutError` — progress polling
        exceeded ``settings.voicebox_generation_timeout_seconds``.
      * Any :class:`voicebox_client.VoiceboxError` subclass bubbling up
        from an underlying HTTP call (unreachable, API error, etc.).
    """
    model_name = model_for_engine(engine)

    # Fast path: cache hit.
    if model_name in _loaded_models:
        return model_name

    lock = _load_locks.setdefault(model_name, asyncio.Lock())
    async with lock:
        # Re-check under lock — another coroutine may have populated the cache.
        if model_name in _loaded_models:
            return model_name

        status = await vb.get_model_status(model_name)
        if status.loaded:
            log.info(
                "ensure_model_loaded: %s already loaded on Voicebox — caching",
                model_name,
            )
            _loaded_models.add(model_name)
            return model_name

        log.info("ensure_model_loaded: requesting load of %s", model_name)
        await vb.load_model(model_name)

        # Poll until terminal state or deadline.
        # Late import avoids a hard dep on settings at module import time.
        from backend.config import get_settings
        timeout = float(get_settings().voicebox_generation_timeout_seconds)
        deadline = _now() + timeout
        while _now() < deadline:
            await asyncio.sleep(1.0)
            p = await vb.get_model_progress(model_name)
            status_lc = (p.status or "").lower()
            if status_lc in {"complete", "completed", "loaded", "ready", "done"}:
                log.info("ensure_model_loaded: %s loaded", model_name)
                _loaded_models.add(model_name)
                return model_name
            if status_lc in {"error", "failed", "errored"}:
                raise vb.VoiceboxModelNotLoaded(
                    f"Model {model_name!r} failed to load: "
                    f"{p.message or '<no message>'}"
                )
            # "loading" / "downloading" / "idle" — keep waiting.

        raise vb.VoiceboxTimeoutError(
            f"Model {model_name!r} did not load within {timeout:.0f}s"
        )


def _reset_cache_for_tests() -> None:
    """Test hook — clear in-process caches. Do not call from production code."""
    _loaded_models.clear()
    _load_locks.clear()
