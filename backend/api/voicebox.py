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

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from backend.schemas import (
    VoiceboxConfigOut,
    VoiceboxConfigUpdate,
    VoiceboxHealthOut,
    VoiceboxTestConnectionRequest,
    VoiceboxTestConnectionResponse,
)
from backend.voices import voicebox_client, voicebox_config_store

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

    # Not configured → short-circuit before calling the client (which
    # would currently raise VoiceboxNotEnabled if disabled or return an
    # "URL not configured" VoiceboxHealth if enabled-without-URL).
    if not configured or not enabled:
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

    try:
        health = await voicebox_client.health_check()
    except voicebox_client.VoiceboxNotEnabled:
        # Race: enabled flag flipped between the store read and the
        # client read. Surface as disabled rather than 500.
        return VoiceboxHealthOut(
            configured=configured,
            enabled=False,
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
        enabled=health.enabled,
        reachable=health.reachable,
        base_url=health.base_url,
        version=health.version,
        profile_count=health.profile_count,
        available_engines=health.available_engines,
        # health_check() doesn't currently parse model_loaded — will be
        # populated once the voicebox_client rewrite (Commit 3) wires it
        # through. Defaulting to False keeps the contract stable.
        model_loaded=False,
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
