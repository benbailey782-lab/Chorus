"""Voicebox REST wrapper — typed HTTP client (Phase 5).

Voicebox is the local TTS backend (Chatterbox / Qwen3-TTS / HumeAI TADA / LuxTTS)
that runs on the Mac alongside Chorus. Phase 2 was built on Windows in stub mode;
Phase 5 introduces the typed HTTP client surface needed by the generation
pipeline (health check, synthesize wrapper, delete_profile) while preserving all
Phase-2 stubs for backwards compatibility.

Every method here:
  * checks ``settings.voicebox_enabled`` and raises :class:`VoiceboxNotEnabled`
    when off;
  * carries a ``TODO(voicebox-verify)`` comment listing the exact endpoint,
    request shape, and response shape this code needs when wiring happens;
  * never raises on import / construction — the application can start without
    Voicebox being reachable.

========================================================================
TODO(voicebox-verify) — assumptions that need to be confirmed against a
running Voicebox ``/docs`` (§12.2 of CHORUS-SPEC.md). Each bullet marks
what's spec-derived vs verified. When Ben gets Voicebox on his Mac, walk
this list top-to-bottom and flip each entry to VERIFIED or patch the
implementation.
========================================================================

  * [SPEC]    GET /api/health exists and returns {"version": str,
              "profile_count": int, "engines": list[str]}.
  * [SPEC]    Fallback health paths: /api/status, /health. We probe in that
              order and accept the first 2xx.
  * [SPEC]    GET /api/profiles → JSON array of profile objects.
  * [SPEC]    POST /api/profiles (multipart) → created profile object.
  * [SPEC]    POST /api/generate → {"generation_id": str, "status": str, ...}.
  * [SPEC]    GET /api/generations/{id} → status shape identical to POST.
  * [SPEC]    GET /api/generations/{id}/audio → binary audio with Content-Type.
  * [SPEC]    DELETE /api/profiles/{id} → 204/200 on success, 404 treated as
              already-gone.
  * [UNKNOWN] Whether ``effects`` / ``engine`` / ``seed`` are accepted by
              POST /api/generate, or must be nested under a per-engine block.
  * [UNKNOWN] Sample-rate negotiation: do we request it via POST body or must
              we resample client-side?
  * [UNKNOWN] Duration / sample_rate reporting: Voicebox may return these in
              the generation status payload, or we may need to decode the
              audio ourselves. SynthesisResult allows either.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    """Raised when VOICEBOX_ENABLED is true but the server doesn't respond.

    Historical name — kept for backwards compatibility with Phase-2 call
    sites. New code should prefer :class:`VoiceboxUnreachableError`.
    """


class VoiceboxUnreachableError(VoiceboxError):
    """Raised when VOICEBOX_ENABLED=True but the server doesn't respond."""


class VoiceboxTimeoutError(VoiceboxError):
    """Raised when a synthesize call exceeds ``voicebox_timeout_seconds``."""


class VoiceboxGenerationFailed(VoiceboxError):
    """Raised when a generation job returns status=error."""


# ---------------------------------------------------------------------------
# Typed shapes (inline; tightly coupled to this module)
# ---------------------------------------------------------------------------


@dataclass
class VoiceboxHealth:
    enabled: bool              # mirrors settings.voicebox_enabled
    reachable: bool            # actually responded
    base_url: str
    version: Optional[str]
    profile_count: Optional[int]
    available_engines: list[str]
    error: Optional[str]


@dataclass
class VoiceboxProfile:
    id: str
    name: str
    metadata: dict[str, Any]


@dataclass
class SynthesisOptions:
    engine: Optional[str] = None
    sample_rate: Optional[int] = None          # defaults to settings.voicebox_output_sample_rate
    seed: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)   # forward-compat per-engine knobs


@dataclass
class SynthesisResult:
    audio_bytes: bytes
    duration_ms: Optional[int]
    sample_rate: Optional[int]
    content_type: Optional[str]


# Backwards-compat status shape used by the old /api/voices/voicebox/status.
@dataclass
class VoiceboxStatus:
    enabled: bool
    reachable: Optional[bool]   # None when disabled
    base_url: str
    note: str


# ---------------------------------------------------------------------------
# Probe / health-check — safe to call whether or not Voicebox is enabled/reachable
# ---------------------------------------------------------------------------


async def probe(settings: Optional[Settings] = None, *, timeout_s: float = 1.5) -> VoiceboxStatus:
    """Return a VoiceboxStatus without raising — safe for use in preflight / UI.

    Preserved for Phase-2 backwards compatibility. New code should call
    :func:`health_check` for the richer :class:`VoiceboxHealth` shape.
    """
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


# Health probe endpoints tried in order — first 2xx wins.
# TODO(voicebox-verify): pick canonical path once Voicebox /docs is in hand.
_HEALTH_PATHS = ("/api/health", "/api/status", "/health")


async def health_check(*, timeout: Optional[float] = None) -> VoiceboxHealth:
    """Returns VoiceboxHealth. Raises VoiceboxNotEnabled if disabled.

    Tries GET /api/health, /api/status, /health in order (Voicebox real API
    unverified — TODO(voicebox-verify)). First one that returns 2xx wins.
    Returns reachable=False + error on network failure instead of raising,
    so the UI banner can render a stable state.
    """
    settings = get_settings()
    if not settings.voicebox_enabled:
        raise VoiceboxNotEnabled(
            "Voicebox is disabled (VOICEBOX_ENABLED=false). "
            "Set it to true and start the Voicebox server to use TTS features."
        )

    t = timeout if timeout is not None else 2.0
    base = settings.voicebox_base_url.rstrip("/")
    last_error: Optional[str] = None

    for path in _HEALTH_PATHS:
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                r = await client.get(base + path)
        except (httpx.ConnectError, httpx.RequestError, httpx.HTTPError) as e:
            last_error = f"{type(e).__name__}: {e!s}"
            continue

        if 200 <= r.status_code < 300:
            # Parse the payload loosely — any of the fields may be missing.
            version: Optional[str] = None
            profile_count: Optional[int] = None
            engines: list[str] = []
            try:
                payload = r.json()
                if isinstance(payload, dict):
                    v = payload.get("version")
                    version = str(v) if v is not None else None
                    pc = payload.get("profile_count")
                    profile_count = int(pc) if isinstance(pc, (int, float)) else None
                    eng = payload.get("engines") or payload.get("available_engines") or []
                    if isinstance(eng, list):
                        engines = [str(x) for x in eng]
            except ValueError:
                # Non-JSON 2xx is still "reachable" — just no metadata.
                pass
            return VoiceboxHealth(
                enabled=True,
                reachable=True,
                base_url=settings.voicebox_base_url,
                version=version,
                profile_count=profile_count,
                available_engines=engines,
                error=None,
            )
        # Non-2xx — remember and try next path.
        last_error = f"HTTP {r.status_code} at {path}"

    return VoiceboxHealth(
        enabled=True,
        reachable=False,
        base_url=settings.voicebox_base_url,
        version=None,
        profile_count=None,
        available_engines=[],
        error=last_error or "no health endpoint responded",
    )


# ---------------------------------------------------------------------------
# Client (low-level endpoints, preserved from Phase 2)
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

        TODO(voicebox-verify): GET /api/profiles
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
            except (httpx.ConnectError, httpx.RequestError) as e:
                raise VoiceboxUnreachableError(f"list_profiles failed: {e!s}") from e
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

        TODO(voicebox-verify): POST /api/profiles  (multipart/form-data)
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
                except (httpx.ConnectError, httpx.RequestError) as e:
                    raise VoiceboxUnreachableError(f"create_profile failed: {e!s}") from e
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

        TODO(voicebox-verify): POST /api/generate
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
            except (httpx.ConnectError, httpx.RequestError) as e:
                raise VoiceboxUnreachableError(f"generate failed: {e!s}") from e
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"generate failed: {e!s}") from e
        return r.json()

    async def get_generation(self, generation_id: str) -> dict[str, Any]:
        """Poll a generation's status/progress.

        TODO(voicebox-verify): GET /api/generations/{generation_id}
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
            except (httpx.ConnectError, httpx.RequestError) as e:
                raise VoiceboxUnreachableError(f"get_generation failed: {e!s}") from e
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"get_generation failed: {e!s}") from e
        return r.json()

    async def download_generation_audio(self, generation_id: str) -> bytes:
        """Fetch the raw audio bytes for a completed generation.

        TODO(voicebox-verify): GET /api/generations/{generation_id}/audio
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
            except (httpx.ConnectError, httpx.RequestError) as e:
                raise VoiceboxUnreachableError(f"download_generation_audio failed: {e!s}") from e
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"download_generation_audio failed: {e!s}") from e
        return r.content

    async def download_generation_audio_with_headers(
        self, generation_id: str
    ) -> tuple[bytes, Optional[str]]:
        """Like ``download_generation_audio`` but also returns Content-Type.

        Internal helper for :func:`synthesize` — the top-level wrapper needs
        the content-type for its :class:`SynthesisResult`.
        """
        self._require_enabled()
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                r = await client.get(self._url(f"/api/generations/{generation_id}/audio"))
                r.raise_for_status()
            except (httpx.ConnectError, httpx.RequestError) as e:
                raise VoiceboxUnreachableError(f"download_generation_audio failed: {e!s}") from e
            except httpx.HTTPError as e:
                raise VoiceboxUnreachable(f"download_generation_audio failed: {e!s}") from e
        return r.content, r.headers.get("content-type")


# ---------------------------------------------------------------------------
# Top-level helpers (Phase 5 additions)
# ---------------------------------------------------------------------------


async def synthesize(
    profile_id: str,
    text: str,
    *,
    options: Optional[SynthesisOptions] = None,
) -> SynthesisResult:
    """Thin synchronous-feeling wrapper over generate → poll → download.

    Polls every ``max(1s, timeout/30)`` up to
    ``settings.voicebox_timeout_seconds``.

    Raises :class:`VoiceboxNotEnabled` / :class:`VoiceboxUnreachableError`
    / :class:`VoiceboxTimeoutError` / :class:`VoiceboxGenerationFailed` as
    appropriate.
    """
    settings = get_settings()
    if not settings.voicebox_enabled:
        raise VoiceboxNotEnabled(
            "Voicebox is disabled (VOICEBOX_ENABLED=false)."
        )

    client = VoiceboxClient(settings)
    opts = options or SynthesisOptions()

    # TODO(voicebox-verify): confirm that sample_rate / seed / extra map into
    # the effects payload rather than top-level POST /api/generate fields.
    effects: dict[str, Any] = dict(opts.extra) if opts.extra else {}
    if opts.sample_rate is not None:
        effects.setdefault("sample_rate", opts.sample_rate)
    else:
        effects.setdefault("sample_rate", settings.voicebox_output_sample_rate)
    if opts.seed is not None:
        effects.setdefault("seed", opts.seed)

    started = await client.generate(
        text=text,
        profile_id=profile_id,
        engine=opts.engine,
        effects=effects or None,
    )
    generation_id = started.get("generation_id") or started.get("id")
    if not generation_id:
        raise VoiceboxGenerationFailed(
            f"Voicebox /api/generate response missing generation_id: {started!r}"
        )

    timeout_s = float(settings.voicebox_timeout_seconds)
    poll_interval = max(1.0, timeout_s / 30.0)
    deadline = asyncio.get_event_loop().time() + timeout_s

    last_payload: dict[str, Any] = started
    while True:
        status = str(last_payload.get("status", "")).lower()
        if status == "done" or status == "complete" or status == "completed":
            break
        if status == "error" or status == "failed":
            msg = last_payload.get("error") or "voicebox reported generation error"
            raise VoiceboxGenerationFailed(f"generation {generation_id}: {msg}")

        if asyncio.get_event_loop().time() >= deadline:
            raise VoiceboxTimeoutError(
                f"generation {generation_id} did not complete within {timeout_s:.0f}s"
            )

        await asyncio.sleep(poll_interval)
        last_payload = await client.get_generation(generation_id)

    audio_bytes, content_type = await client.download_generation_audio_with_headers(generation_id)

    # Voicebox may return duration_ms / sample_rate in the status payload —
    # TODO(voicebox-verify) confirms this. Fall back to None if absent.
    duration_ms = last_payload.get("duration_ms")
    if duration_ms is not None:
        try:
            duration_ms = int(duration_ms)
        except (TypeError, ValueError):
            duration_ms = None
    sample_rate = last_payload.get("sample_rate") or effects.get("sample_rate")
    if sample_rate is not None:
        try:
            sample_rate = int(sample_rate)
        except (TypeError, ValueError):
            sample_rate = None

    return SynthesisResult(
        audio_bytes=audio_bytes,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        content_type=content_type,
    )


async def delete_profile(profile_id: str) -> None:
    """DELETE /api/profiles/{id}. Best-effort; 404 = ok (already gone).

    TODO(voicebox-verify): exact status codes / idempotency semantics.
    """
    settings = get_settings()
    if not settings.voicebox_enabled:
        raise VoiceboxNotEnabled(
            "Voicebox is disabled (VOICEBOX_ENABLED=false)."
        )
    url = settings.voicebox_base_url.rstrip("/") + f"/api/profiles/{profile_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.delete(url)
        except (httpx.ConnectError, httpx.RequestError) as e:
            raise VoiceboxUnreachableError(f"delete_profile failed: {e!s}") from e
    if r.status_code == 404:
        return  # already gone — treat as success
    if not (200 <= r.status_code < 300):
        raise VoiceboxError(
            f"delete_profile {profile_id} returned HTTP {r.status_code}: {r.text[:200]}"
        )
