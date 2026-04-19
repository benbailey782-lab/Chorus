"""Voicebox health / control / config surface (§12.2).

Phase 5 promoted the TTS-backend status probe from
``/api/voices/voicebox/status`` to ``/api/voicebox``. Phase 5 remediation
adds:

  * ``GET  /api/voicebox/status``            — extended shape (configured +
                                                model_loaded fields).
  * ``POST /api/voicebox/test-connection``   — probe an arbitrary URL
                                                without persisting anything.
  * ``PATCH /api/voicebox/config``           — write base_url + enabled to
                                                ``data/voicebox_config.json``.

Reading is routed through
:func:`backend.voices.voicebox_config_store.get_effective` on every
request so UI saves take effect without a backend restart (the
``Settings`` lru_cache stays intact; only Voicebox reads go through the
store).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.schemas import (
    ModelProgressOut,
    ModelStatusOut,
    VoiceboxConfigOut,
    VoiceboxConfigUpdate,
    VoiceboxHealthOut,
    VoiceboxTestConnectionRequest,
    VoiceboxTestConnectionResponse,
)
from backend.voices import voicebox_client, voicebox_config_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voicebox", tags=["voicebox"])


# ---------------------------------------------------------------------------
# GET /api/voicebox/status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=VoiceboxHealthOut)
async def get_voicebox_status() -> VoiceboxHealthOut:
    """Canonical voicebox health endpoint.

    Short-circuits to a "not configured" / "disabled" shape when the
    operator hasn't saved a URL or flipped the enabled toggle. When
    enabled + configured, delegates to
    :func:`voicebox_client.health_check` and surfaces transport errors
    via the ``error`` field.
    """
    base_url, enabled = voicebox_config_store.get_effective()
    configured = bool(base_url.strip())

    # Not configured → short-circuit before calling the client.
    if not configured:
        return VoiceboxHealthOut(
            configured=configured,
            enabled=enabled,
            reachable=False,
            base_url=base_url,
            version=None,
            profile_count=None,
            available_engines=[],
            model_loaded=False,
            error=None,
        )

    # Configured but disabled → still probe so the UI can show the
    # actual reachability state of the saved URL (helps the operator
    # notice a dead Voicebox before flipping the toggle).
    try:
        health = await voicebox_client.health_check(base_url=base_url)
    except voicebox_client.VoiceboxNotConfigured:
        return VoiceboxHealthOut(
            configured=configured,
            enabled=enabled,
            reachable=False,
            base_url=base_url,
            version=None,
            profile_count=None,
            available_engines=[],
            model_loaded=False,
            error=None,
        )

    return VoiceboxHealthOut(
        configured=configured,
        enabled=enabled,
        reachable=health.reachable,
        base_url=health.base_url,
        version=health.version,
        profile_count=health.profile_count,
        available_engines=health.available_engines,
        model_loaded=health.model_loaded,
        error=health.error,
    )


# ---------------------------------------------------------------------------
# POST /api/voicebox/test-connection
# ---------------------------------------------------------------------------


# Paths we try in order when probing an arbitrary URL. Voicebox v0.4.0
# serves ``/health``; older Voicebox-shaped stubs may serve ``/api/health``
# or ``/api/status``. First 2xx wins. Matches the fallback strategy in
# health_check().
_TEST_PATHS = ("/health", "/api/health", "/api/status")


def _parse_voicebox_health_payload(payload: Any) -> dict[str, Any]:
    """Extract Voicebox /health fields with loose typing.

    Every field is optional — we fall back to the response-model defaults
    if anything is missing. Voicebox v0.4.0's /health returns
    ``{version, models_loaded: int, gpu_available: bool,
    model_loaded: bool}``; older shapes may surface ``profile_count`` or
    ``engines`` instead.
    """
    out: dict[str, Any] = {}
    if not isinstance(payload, dict):
        return out
    if (v := payload.get("version")) is not None:
        out["version"] = str(v)
    if isinstance(payload.get("models_loaded"), (int, float)):
        out["models_loaded"] = int(payload["models_loaded"])
    if isinstance(payload.get("gpu_available"), bool):
        out["gpu_available"] = payload["gpu_available"]
    if isinstance(payload.get("model_loaded"), bool):
        out["model_loaded"] = payload["model_loaded"]
    if isinstance(payload.get("profile_count"), (int, float)):
        out["profile_count"] = int(payload["profile_count"])
    return out


@router.post("/test-connection", response_model=VoiceboxTestConnectionResponse)
async def test_voicebox_connection(
    body: VoiceboxTestConnectionRequest,
) -> VoiceboxTestConnectionResponse:
    """Probe an arbitrary URL to see if it hosts a Voicebox server.

    Does NOT touch saved config. Used by the Settings > Voicebox UI for
    the "Test connection" button.
    """
    url = (body.url or "").strip()
    if not url:
        return VoiceboxTestConnectionResponse(
            reachable=False,
            error="URL is empty",
        )

    base = url.rstrip("/")
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=5.0) as client:
        for path in _TEST_PATHS:
            try:
                r = await client.get(base + path)
            except (httpx.ConnectError, httpx.RequestError, httpx.HTTPError) as e:
                last_error = f"{type(e).__name__}: {e!s}"
                continue

            if not (200 <= r.status_code < 300):
                last_error = f"HTTP {r.status_code} at {path}"
                continue

            # Got a 2xx — parse loosely. Non-JSON bodies still count as
            # reachable, just with no metadata.
            payload: Any = None
            try:
                payload = r.json()
            except ValueError:
                payload = None
            fields = _parse_voicebox_health_payload(payload)
            return VoiceboxTestConnectionResponse(
                reachable=True,
                version=fields.get("version"),
                models_loaded=fields.get("models_loaded", 0),
                gpu_available=fields.get("gpu_available", False),
                model_loaded=fields.get("model_loaded", False),
                profile_count=fields.get("profile_count", 0),
                error=None,
            )

    return VoiceboxTestConnectionResponse(
        reachable=False,
        error=last_error or "no health endpoint responded",
    )


# ---------------------------------------------------------------------------
# PATCH /api/voicebox/config
# ---------------------------------------------------------------------------


@router.patch("/config", response_model=VoiceboxConfigOut)
async def update_voicebox_config(body: VoiceboxConfigUpdate) -> VoiceboxConfigOut:
    """Persist Voicebox URL + enabled flag to ``data/voicebox_config.json``.

    Validation:
      * ``enabled=True`` with an empty effective URL → 400.

    Unset fields fall back to the currently-saved values so the UI can
    send just the delta (e.g. toggling enabled without resending the
    URL).
    """
    current_url, current_enabled = voicebox_config_store.get_effective()

    new_url = body.base_url if body.base_url is not None else current_url
    new_url = (new_url or "").strip()
    new_enabled = body.enabled if body.enabled is not None else current_enabled

    if new_enabled and not new_url:
        raise HTTPException(
            status_code=400,
            detail="URL required to enable Voicebox",
        )

    voicebox_config_store.save(base_url=new_url, enabled=bool(new_enabled))

    # Return the *effective* state — re-read through the store so the UI
    # sees exactly what subsequent reads will see.
    eff_url, eff_enabled = voicebox_config_store.get_effective()
    return VoiceboxConfigOut(
        base_url=eff_url,
        enabled=eff_enabled,
        configured=bool(eff_url.strip()),
    )


# ---------------------------------------------------------------------------
# Model status + progress + load/unload (Phase-5R Commit 6)
# ---------------------------------------------------------------------------
#
# These proxy the underlying Voicebox ``/models/*`` endpoints through the
# typed ``voicebox_client`` so the frontend has a single backend origin to
# talk to (matching every other Voicebox surface). The frontend's
# ``ModelLoadingBanner`` polls ``/api/voicebox/models/{name}/progress`` while
# a load is in-flight; the Chapter-Review generation pre-flight check uses
# ``/api/voicebox/models`` to decide whether to surface a "first load may
# take 2-4 minutes" warning before kicking a chapter generation.
#
# When Voicebox is disabled or unreachable we translate the client's
# typed exceptions into appropriate HTTP status codes so the UI can render
# a helpful message (503 for disabled/unreachable so the browser fetch
# error surface lines up with the VoiceboxStatusBanner messaging).


def _voicebox_http_error(e: voicebox_client.VoiceboxError) -> HTTPException:
    """Map a typed Voicebox client error → FastAPI HTTPException.

    * Not configured / not enabled → 503 (the saved config won't let us talk
      to Voicebox; UI should point the operator at Settings).
    * Unreachable / timeout → 503 (Voicebox itself is down).
    * API error → 502 (Voicebox responded but returned an error payload;
      forward the status in the detail so the operator can see it).
    * Anything else → 502 fallback.
    """
    if isinstance(e, voicebox_client.VoiceboxNotConfigured):
        return HTTPException(status_code=503, detail=f"Voicebox not configured: {e}")
    if isinstance(e, voicebox_client.VoiceboxNotEnabled):
        return HTTPException(status_code=503, detail=f"Voicebox disabled: {e}")
    if isinstance(
        e,
        (voicebox_client.VoiceboxUnreachableError, voicebox_client.VoiceboxTimeoutError),
    ):
        return HTTPException(status_code=503, detail=f"Voicebox unreachable: {e}")
    if isinstance(e, voicebox_client.VoiceboxAPIError):
        return HTTPException(status_code=502, detail=f"Voicebox API error: {e}")
    return HTTPException(status_code=502, detail=f"Voicebox error: {e}")


@router.get("/models", response_model=list[ModelStatusOut])
async def list_voicebox_models() -> list[ModelStatusOut]:
    """List Voicebox models + their loaded/downloaded state.

    Returns the full models catalog. Empty list is valid (no models
    downloaded yet). Callers that only care about a specific model should
    still request this list and filter client-side — Voicebox does not
    expose a by-name probe.
    """
    try:
        rows = await voicebox_client.list_models()
    except voicebox_client.VoiceboxError as e:
        raise _voicebox_http_error(e) from e
    return [
        ModelStatusOut(
            name=m.name,
            loaded=m.loaded,
            downloaded=m.downloaded,
            status=m.status,
        )
        for m in rows
    ]


@router.get(
    "/models/{model_name}/progress",
    response_model=ModelProgressOut,
)
async def get_voicebox_model_progress(model_name: str) -> ModelProgressOut:
    """Return the current progress snapshot for a model load/download.

    Polled once per second by the ModelLoadingBanner while a load is in
    flight. Status vocabulary:
    ``loading|downloading|complete|loaded|error|idle``.
    """
    try:
        p = await voicebox_client.get_model_progress(model_name)
    except voicebox_client.VoiceboxError as e:
        raise _voicebox_http_error(e) from e
    return ModelProgressOut(
        model_name=p.model_name,
        status=p.status,
        progress=p.progress,
        message=p.message,
    )


@router.post("/models/{model_name}/load", status_code=202)
async def load_voicebox_model(model_name: str) -> Response:
    """Kick a Voicebox model load and return 202 immediately.

    The actual load runs on Voicebox's side (can take 2-4 minutes for a
    cold model). UI should immediately start polling
    ``/models/{name}/progress`` via the ModelLoadingBanner.

    We fire-and-forget the POST so the HTTP response here doesn't have to
    wait for the load to finish — ``asyncio.create_task`` keeps the
    coroutine alive until Voicebox replies. Any exception raised by the
    task is logged but swallowed (the UI sees the real state via
    progress polling).
    """

    async def _kick() -> None:
        try:
            await voicebox_client.load_model(model_name)
        except voicebox_client.VoiceboxError as exc:
            log.warning(
                "Voicebox load_model(%s) failed in background: %s",
                model_name,
                exc,
            )

    # Validate config eagerly so an unconfigured Voicebox returns 503 here
    # instead of silently swallowing the failure in the background task.
    base, enabled = voicebox_config_store.get_effective()
    if not base.strip():
        raise HTTPException(
            status_code=503,
            detail="Voicebox not configured. Set a URL in Settings > Voicebox.",
        )
    if not enabled:
        raise HTTPException(status_code=503, detail="Voicebox disabled.")

    asyncio.create_task(_kick())
    return Response(status_code=202)


@router.post("/models/{model_name}/unload", status_code=204)
async def unload_voicebox_model(model_name: str) -> Response:
    """Unload a Voicebox model. Blocks until Voicebox returns — unload is
    fast (no disk work), so we don't need the fire-and-forget dance that
    load_model uses."""
    try:
        await voicebox_client.unload_model(model_name)
    except voicebox_client.VoiceboxError as e:
        raise _voicebox_http_error(e) from e
    return Response(status_code=204)
