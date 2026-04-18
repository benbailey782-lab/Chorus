"""Voicebox REST wrapper — stub mode for Windows dev (Phase 2).

Voicebox is the local TTS backend (Chatterbox / Qwen3-TTS / HumeAI TADA / LuxTTS)
that runs on the Mac alongside Chorus. Phase 2 is being built on Windows without
Voicebox installed, so every method here:

  * checks ``settings.voicebox_enabled`` and raises :class:`VoiceboxNotEnabled`
    when off;
  * carries a ``TODO(voicebox)`` comment listing the exact endpoint, request
    shape, and response shape this code needs when wiring happens;
  * never raises on import / construction — the application can start without
    Voicebox being reachable.

See ``docs/VOICEBOX-WIRING.md`` for the per-call wiring checklist. Expected
endpoint surface is §12.2 of ``CHORUS-SPEC.md``; treat that table as tentative
until verified against a running Voicebox ``/docs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from backend.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VoiceboxError(RuntimeError):
    """Base class for Voicebox-related failures."""


class VoiceboxNotEnabled(VoiceboxError):
    """Raised when ``VOICEBOX_ENABLED`` is false and TTS features are invoked.

    Frontend should map this to a friendly "Voicebox offline" notice.
    """


class VoiceboxUnreachable(VoiceboxError):
    """Raised when VOICEBOX_ENABLED is true but the server doesn't respond."""


# ---------------------------------------------------------------------------
# Status probe — safe to call whether or not Voicebox is enabled/reachable
# ---------------------------------------------------------------------------


@dataclass
class VoiceboxStatus:
    enabled: bool
    reachable: Optional[bool]   # None when disabled
    base_url: str
    note: str


async def probe(settings: Optional[Settings] = None, *, timeout_s: float = 1.5) -> VoiceboxStatus:
    """Return a VoiceboxStatus without raising — safe for use in preflight / UI."""
    settings = settings or get_settings()
    if not settings.voicebox_enabled:
        return VoiceboxStatus(
            enabled=False,
            reachable=None,
            base_url=settings.voicebox_base_url,
            note="Voicebox not configured (VOICEBOX_ENABLED=false) — voice generation features disabled.",
        )
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(settings.voicebox_base_url.rstrip("/") + "/")
            reachable = 200 <= r.status_code < 500
    except Exception as e:  # noqa: BLE001 — any transport error means unreachable
        return VoiceboxStatus(
            enabled=True,
            reachable=False,
            base_url=settings.voicebox_base_url,
            note=f"Voicebox enabled but unreachable at {settings.voicebox_base_url}: {e!s}",
        )
    return VoiceboxStatus(
        enabled=True,
        reachable=reachable,
        base_url=settings.voicebox_base_url,
        note="Voicebox reachable." if reachable else "Voicebox returned an unexpected status.",
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class VoiceboxClient:
    """Thin async wrapper around the Voicebox REST API.

    In stub mode (``VOICEBOX_ENABLED=false``) every call raises
    :class:`VoiceboxNotEnabled`. When enabled, each method performs a real HTTP
    request with the exact shape documented at the call-site.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    # -- internal helpers ------------------------------------------------

    def _require_enabled(self) -> None:
        if not self._settings.voicebox_enabled:
            raise VoiceboxNotEnabled(
                "Voicebox is disabled (VOICEBOX_ENABLED=false). "
                "Set it to true and start the Voicebox server to use TTS features."
            )

    def _url(self, path: str) -> str:
        return self._settings.voicebox_base_url.rstrip("/") + path

    # -- endpoints (§12.2) ----------------------------------------------

    async def list_profiles(self) -> list[dict[str, Any]]:
        """List all TTS profiles known to Voicebox.

        TODO(voicebox): GET /api/profiles
          * Request:  (no body)
          * Response: JSON array of profile objects. Expected shape per profile:
              {"id": str, "display_name": str, "engine": str,
               "created_at": str ISO-8601, "sample_url": str | null}
          * Used by: Chorus does NOT auto-sync this list in v1 — the Chorus
            voice library is the source of truth. This method exists for
            debugging and future reconciliation UIs.
        """
        self._require_enabled()
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                r = await client.get(self._url("/api/profiles"))
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"list_profiles failed: {e!s}") from e
        return r.json()

    async def create_profile(
        self,
        *,
        display_name: str,
        audio_path: Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Upload a reference audio clip and create a cloned voice profile.

        TODO(voicebox): POST /api/profiles  (multipart/form-data)
          * Request fields:
              audio:        file part — WAV/MP3/FLAC/M4A/OGG, up to 25 MB
              display_name: string (human label for Voicebox admin UI)
              metadata:     optional JSON string — we pass §7.2 fields through
                            so Voicebox can store engine preferences alongside
                            the clone
          * Response: the newly-created profile object:
              {"id": str,               # Voicebox profile id — save as
                                        #   voices.voicebox_profile_id
               "display_name": str,
               "engine": str,
               "sample_url": str | null,
               "created_at": str}
          * Called from: backend/api/voices.py after a Chorus voice is created
            or has its reference audio replaced. Stores returned id on the
            voices row.
        """
        self._require_enabled()
        if not audio_path.exists():
            raise VoiceboxError(f"reference audio file missing: {audio_path}")

        import json as _json

        with audio_path.open("rb") as f:
            files = {"audio": (audio_path.name, f, "application/octet-stream")}
            data: dict[str, Any] = {"display_name": display_name}
            if metadata is not None:
                data["metadata"] = _json.dumps(metadata, ensure_ascii=False)
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    r = await client.post(self._url("/api/profiles"), data=data, files=files)
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    raise VoiceboxUnreachable(f"create_profile failed: {e!s}") from e
        return r.json()

    async def generate(
        self,
        *,
        text: str,
        profile_id: str,
        engine: Optional[str] = None,
        effects: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Kick off a TTS generation. Returns a generation handle (likely async).

        TODO(voicebox): POST /api/generate
          * Request (JSON):
              {"text": str,
               "profile_id": str,
               "engine": str | null,   # chatterbox_turbo | qwen3_tts | humeai_tada | luxtts
               "effects": dict | null}  # Chorus passes render-mode-derived
                                        # effects here: reverb, paper_filter,
                                        # pre_silence_ms, post_silence_ms, etc.
          * Response:
              {"generation_id": str,
               "status": "queued" | "running" | "done" | "error",
               "progress": float 0..1,
               "audio_url": str | null}   # populated once status == "done"
        """
        self._require_enabled()
        payload: dict[str, Any] = {"text": text, "profile_id": profile_id}
        if engine is not None:
            payload["engine"] = engine
        if effects is not None:
            payload["effects"] = effects
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(self._url("/api/generate"), json=payload)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"generate failed: {e!s}") from e
        return r.json()

    async def get_generation(self, generation_id: str) -> dict[str, Any]:
        """Poll a generation's status/progress.

        TODO(voicebox): GET /api/generations/{generation_id}
          * Request:  (no body)
          * Response (same shape as POST /api/generate response):
              {"generation_id": str,
               "status": "queued" | "running" | "done" | "error",
               "progress": float 0..1,
               "audio_url": str | null,
               "error": str | null}
        """
        self._require_enabled()
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                r = await client.get(self._url(f"/api/generations/{generation_id}"))
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"get_generation failed: {e!s}") from e
        return r.json()

    async def download_generation_audio(self, generation_id: str) -> bytes:
        """Fetch the raw audio bytes for a completed generation.

        TODO(voicebox): GET /api/generations/{generation_id}/audio
          * Request:  (no body)
          * Response: binary audio file (WAV or MP3 — Voicebox's choice; the
            HTTP Content-Type header tells us which). Chorus writes this to
            ``data/projects/<slug>/segments/<segment_id>.<ext>``.
        """
        self._require_enabled()
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                r = await client.get(self._url(f"/api/generations/{generation_id}/audio"))
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"download_generation_audio failed: {e!s}") from e
        return r.content
