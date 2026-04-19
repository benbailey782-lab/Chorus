"""Voicebox health / control surface (§12.2).

Phase 5 promotes the TTS-backend status probe from
``/api/voices/voicebox/status`` to a dedicated router at ``/api/voicebox``
so the generation pipeline has a logical home that isn't nested under
voice-library CRUD. The old path now 308-redirects here (see
``backend/api/voices.py``).

Uses the richer :class:`VoiceboxHealthOut` shape returned by
:func:`backend.voices.voicebox_client.health_check`.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import VoiceboxHealthOut
from backend.voices import voicebox_client

router = APIRouter(prefix="/api/voicebox", tags=["voicebox"])


@router.get("/status", response_model=VoiceboxHealthOut)
async def get_voicebox_status() -> VoiceboxHealthOut:
    """Canonical voicebox health endpoint.

    Returns a populated :class:`VoiceboxHealthOut` whether or not Voicebox
    is reachable — the probe catches transport errors and reports them via
    the ``error`` field so the UI banner renders a stable state.
    """
    try:
        health = await voicebox_client.health_check()
    except voicebox_client.VoiceboxNotEnabled:
        # Voicebox disabled — return a "disabled" shape so the UI can render
        # without surfacing the exception.
        from backend.config import get_settings
        settings = get_settings()
        return VoiceboxHealthOut(
            enabled=False,
            reachable=False,
            base_url=settings.voicebox_base_url,
            version=None,
            profile_count=None,
            available_engines=[],
            error=None,
        )
    return VoiceboxHealthOut(
        enabled=health.enabled,
        reachable=health.reachable,
        base_url=health.base_url,
        version=health.version,
        profile_count=health.profile_count,
        available_engines=health.available_engines,
        error=health.error,
    )
