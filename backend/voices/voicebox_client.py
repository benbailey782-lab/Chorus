"""Voicebox HTTP client — Voicebox v0.4.0 API.

Verified against Voicebox v0.4.0 ``/openapi.json`` on 2026-04-18. No
``TODO(voicebox-verify)`` markers — every endpoint, request body, and
response shape in this module is a live shape pulled from the running
Voicebox instance.

Design notes
------------

* **Per-call client construction.** Every request builds a fresh
  :class:`httpx.AsyncClient` via :func:`_client` / :func:`_probe_client`.
  URL / enabled state is read through
  :func:`backend.voices.voicebox_config_store.get_effective` on every
  call, which re-reads ``data/voicebox_config.json`` from disk — so
  UI-saved URL changes take effect without a backend restart.
* **Error hierarchy.** Legacy names (:class:`VoiceboxNotEnabled`,
  :class:`VoiceboxUnreachableError`) are kept as aliases / subclasses so
  Phase-5 call sites in ``backend/audio/generation.py`` keep working
  until they get rewritten in Commit 4.
* **No ``/api/`` prefix.** Phase-5's spec-derived client guessed at
  ``/api/...`` paths; Voicebox v0.4.0 serves at root (``/health``,
  ``/profiles``, ``/generate``, ``/audio/{id}``, ...).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from backend.config import get_settings
from backend.voices.voicebox_config_store import get_effective as _get_effective


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VoiceboxError(RuntimeError):
    """Base class for Voicebox client failures."""


class VoiceboxNotConfigured(VoiceboxError):
    """Raised when no URL is saved in config or env."""


class VoiceboxDisabled(VoiceboxError):
    """Raised when Voicebox is configured but explicitly disabled."""


class VoiceboxNotEnabled(VoiceboxDisabled):
    """Legacy alias for :class:`VoiceboxDisabled`.

    Kept for Phase-5 call sites (``backend/audio/generation.py``) that
    import this name. New code should prefer :class:`VoiceboxDisabled`.
    """


class VoiceboxUnreachable(VoiceboxError):
    """Raised when the Voicebox HTTP endpoint is unreachable / times out."""


class VoiceboxUnreachableError(VoiceboxUnreachable):
    """Legacy alias for :class:`VoiceboxUnreachable`.

    Kept for Phase-5 call sites. New code should prefer
    :class:`VoiceboxUnreachable`.
    """


class VoiceboxAPIError(VoiceboxError):
    """Raised when Voicebox returns a non-2xx response."""

    def __init__(self, message: str, *, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class VoiceboxGenerationError(VoiceboxError):
    """Raised when a generation job reports status=failed."""


class VoiceboxGenerationFailed(VoiceboxGenerationError):
    """Legacy alias for :class:`VoiceboxGenerationError`."""


class VoiceboxTimeoutError(VoiceboxError):
    """Raised when ``generate_and_wait`` exceeds its polling deadline."""


class VoiceboxModelNotLoaded(VoiceboxError):
    """Raised when the engine's backing model is not loaded on Voicebox."""


# ---------------------------------------------------------------------------
# Dataclasses (response shapes)
# ---------------------------------------------------------------------------


@dataclass
class VoiceboxHealth:
    """Snapshot of Voicebox reachability + capability.

    ``configured`` / ``enabled`` come from our config store; everything
    else comes from Voicebox's ``GET /health`` response. On network
    failure all optional fields are ``None`` / defaults and ``error``
    describes the failure.
    """

    configured: bool
    enabled: bool
    reachable: bool
    base_url: str
    version: Optional[str]
    profile_count: Optional[int]
    available_engines: list[str]
    gpu_available: bool
    model_loaded: bool
    error: Optional[str]


@dataclass
class ModelStatus:
    """One row of ``GET /models/status``'s ``models`` array."""

    name: str                       # Voicebox's ``model_name``
    display_name: str
    loaded: bool
    downloaded: bool
    downloading: bool
    size_mb: Optional[float]
    hf_repo_id: Optional[str]
    status: Optional[str]           # derived: "loaded"|"downloading"|"downloaded"|"missing"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelProgress:
    """Progress snapshot for a model load/download."""

    model_name: str
    status: str                      # "loading"|"downloading"|"complete"|"error"|"idle"
    progress: float                  # 0.0-1.0 (normalized from Voicebox which may emit 0-100)
    message: Optional[str]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceboxProfile:
    """A Voicebox voice profile."""

    id: str
    name: str
    engine: Optional[str]
    samples: list[dict[str, Any]]
    created_at: Optional[str]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceboxSample:
    """One reference sample attached to a :class:`VoiceboxProfile`."""

    id: str
    profile_id: str
    path: Optional[str]
    label: Optional[str]
    duration_ms: Optional[int]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PresetVoice:
    """A built-in preset voice for a given engine."""

    id: str
    name: str
    engine: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResponse:
    """Initial POST /generate response (id + status)."""

    generation_id: str
    status: str                      # "queued"|"running"|"complete"|"completed"|"failed"|"cancelled"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationStatus:
    """Polling snapshot for an in-flight generation."""

    generation_id: str
    status: str
    progress: float                  # 0.0-1.0
    duration_ms: Optional[int]
    error: Optional[str]
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Legacy compat shims — kept so Phase 5 ``backend/audio/generation.py`` keeps
# importing until Commit 4 rewrites it. Remove these in Commit 4.
# ---------------------------------------------------------------------------


@dataclass
class SynthesisOptions:
    """Legacy Phase-5 options bundle used by ``synthesize``."""

    engine: Optional[str] = None
    sample_rate: Optional[int] = None
    seed: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisResult:
    """Legacy Phase-5 synthesis result returned by ``synthesize``."""

    audio_bytes: bytes
    duration_ms: Optional[int]
    sample_rate: Optional[int]
    content_type: Optional[str]


@dataclass
class VoiceboxStatus:
    """Legacy Phase-2 status tuple returned by ``probe``."""

    enabled: bool
    reachable: Optional[bool]
    base_url: str
    note: str


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------


def _client() -> httpx.AsyncClient:
    """Build an AsyncClient bound to the effective Voicebox URL.

    Raises :class:`VoiceboxNotConfigured` if no URL is set,
    :class:`VoiceboxNotEnabled` if Voicebox is disabled.
    """
    base, enabled = _get_effective()
    if not base:
        raise VoiceboxNotConfigured(
            "Voicebox URL is not configured. Set it in Settings > Voicebox."
        )
    if not enabled:
        raise VoiceboxNotEnabled(
            "Voicebox is disabled. Enable it in Settings > Voicebox."
        )
    timeout = float(get_settings().voicebox_timeout_seconds)
    return httpx.AsyncClient(base_url=base.rstrip("/"), timeout=timeout)


def _probe_client(
    base_url: Optional[str] = None, *, timeout: float = 5.0
) -> httpx.AsyncClient:
    """Build an AsyncClient for health/test probes.

    Does NOT require ``enabled=True``. If ``base_url`` is given it wins;
    otherwise falls back to the effective config.
    """
    if base_url is None or not base_url.strip():
        base_url, _ = _get_effective()
    if not base_url:
        raise VoiceboxNotConfigured("Voicebox URL is not set")
    return httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)


def _raise_for_status(r: httpx.Response, *, op: str) -> None:
    """Raise :class:`VoiceboxAPIError` on non-2xx with body preview."""
    if 200 <= r.status_code < 300:
        return
    body = ""
    try:
        body = r.text[:500]
    except Exception:  # noqa: BLE001
        body = ""
    raise VoiceboxAPIError(
        f"{op} returned HTTP {r.status_code}: {body}",
        status_code=r.status_code,
        body=body,
    )


async def _do(coro, *, op: str) -> httpx.Response:
    """Run an awaitable httpx call and wrap transport errors."""
    try:
        return await coro
    except httpx.TimeoutException as e:
        raise VoiceboxUnreachable(f"{op} timed out: {e!s}") from e
    except (httpx.ConnectError, httpx.RequestError, httpx.HTTPError) as e:
        raise VoiceboxUnreachable(f"{op} failed: {type(e).__name__}: {e!s}") from e


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def health_check(
    base_url: Optional[str] = None, *, timeout: float = 5.0
) -> VoiceboxHealth:
    """Return a :class:`VoiceboxHealth` snapshot.

    Never raises on network errors — returns ``reachable=False`` +
    ``error`` instead. Only raises :class:`VoiceboxNotConfigured` when
    neither ``base_url`` nor the config store provides a URL.

    If ``base_url`` is provided, uses it verbatim (for the
    Settings > Voicebox "Test connection" flow). Otherwise reads from
    the config store.
    """
    cfg_url, cfg_enabled = _get_effective()
    effective_url = (base_url or cfg_url or "").strip()
    configured = bool(effective_url)
    enabled = cfg_enabled if base_url is None else True  # ad-hoc probe = "enabled" for that URL

    if not configured:
        raise VoiceboxNotConfigured("Voicebox URL is not set")

    try:
        async with _probe_client(effective_url, timeout=timeout) as client:
            r = await _do(client.get("/health"), op="health_check GET /health")
    except VoiceboxUnreachable as e:
        return VoiceboxHealth(
            configured=configured,
            enabled=enabled,
            reachable=False,
            base_url=effective_url,
            version=None,
            profile_count=None,
            available_engines=[],
            gpu_available=False,
            model_loaded=False,
            error=str(e),
        )

    if not (200 <= r.status_code < 300):
        return VoiceboxHealth(
            configured=configured,
            enabled=enabled,
            reachable=False,
            base_url=effective_url,
            version=None,
            profile_count=None,
            available_engines=[],
            gpu_available=False,
            model_loaded=False,
            error=f"HTTP {r.status_code} at /health",
        )

    # /health returned 2xx — parse loosely.
    payload: dict[str, Any] = {}
    try:
        raw = r.json()
        if isinstance(raw, dict):
            payload = raw
    except ValueError:
        pass

    version = payload.get("version")
    version_s = str(version) if version is not None else None

    profile_count_raw = payload.get("profile_count")
    profile_count = (
        int(profile_count_raw)
        if isinstance(profile_count_raw, (int, float))
        else None
    )

    engines_raw = (
        payload.get("available_engines")
        or payload.get("engines")
        or []
    )
    engines: list[str] = (
        [str(x) for x in engines_raw] if isinstance(engines_raw, list) else []
    )

    return VoiceboxHealth(
        configured=configured,
        enabled=enabled,
        reachable=True,
        base_url=effective_url,
        version=version_s,
        profile_count=profile_count,
        available_engines=engines,
        gpu_available=bool(payload.get("gpu_available", False)),
        model_loaded=bool(payload.get("model_loaded", False)),
        error=None,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _parse_model_status(row: dict[str, Any]) -> ModelStatus:
    name = str(row.get("model_name") or row.get("name") or "")
    display = str(row.get("display_name") or name)
    loaded = bool(row.get("loaded", False))
    downloaded = bool(row.get("downloaded", False))
    downloading = bool(row.get("downloading", False))
    size_mb_raw = row.get("size_mb")
    size_mb = (
        float(size_mb_raw)
        if isinstance(size_mb_raw, (int, float))
        else None
    )
    hf_repo = row.get("hf_repo_id")
    hf_repo_s = str(hf_repo) if hf_repo else None

    if loaded:
        status = "loaded"
    elif downloading:
        status = "downloading"
    elif downloaded:
        status = "downloaded"
    else:
        status = "missing"

    # Forward-compat: squirrel away any other fields.
    known = {
        "model_name", "name", "display_name", "loaded", "downloaded",
        "downloading", "size_mb", "hf_repo_id",
    }
    extra = {k: v for k, v in row.items() if k not in known}

    return ModelStatus(
        name=name,
        display_name=display,
        loaded=loaded,
        downloaded=downloaded,
        downloading=downloading,
        size_mb=size_mb,
        hf_repo_id=hf_repo_s,
        status=status,
        extra=extra,
    )


async def list_models() -> list[ModelStatus]:
    """``GET /models/status`` → list of :class:`ModelStatus`."""
    async with _client() as client:
        r = await _do(client.get("/models/status"), op="list_models")
    _raise_for_status(r, op="list_models")
    payload = r.json()
    rows = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise VoiceboxAPIError(
            f"list_models: expected list of models, got {type(rows).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return [_parse_model_status(row) for row in rows if isinstance(row, dict)]


async def get_model_status(model_name: str) -> ModelStatus:
    """Filter :func:`list_models` by ``model_name``.

    Raises :class:`VoiceboxAPIError` if the model isn't present.
    """
    for m in await list_models():
        if m.name == model_name:
            return m
    raise VoiceboxAPIError(
        f"model {model_name!r} not found",
        status_code=404,
        body="",
    )


async def load_model(model_name: str) -> None:
    """``POST /models/load {model_name}``."""
    async with _client() as client:
        r = await _do(
            client.post("/models/load", json={"model_name": model_name}),
            op=f"load_model({model_name})",
        )
    _raise_for_status(r, op=f"load_model({model_name})")


async def unload_model(model_name: str) -> None:
    """``POST /models/{model_name}/unload``."""
    async with _client() as client:
        r = await _do(
            client.post(f"/models/{model_name}/unload"),
            op=f"unload_model({model_name})",
        )
    _raise_for_status(r, op=f"unload_model({model_name})")


async def download_model(model_name: str) -> None:
    """``POST /models/download {model_name}``."""
    async with _client() as client:
        r = await _do(
            client.post("/models/download", json={"model_name": model_name}),
            op=f"download_model({model_name})",
        )
    _raise_for_status(r, op=f"download_model({model_name})")


async def get_model_progress(model_name: str) -> ModelProgress:
    """``GET /models/progress/{model_name}``."""
    async with _client() as client:
        r = await _do(
            client.get(f"/models/progress/{model_name}"),
            op=f"get_model_progress({model_name})",
        )
    _raise_for_status(r, op=f"get_model_progress({model_name})")

    payload: dict[str, Any] = {}
    try:
        raw = r.json()
        if isinstance(raw, dict):
            payload = raw
    except ValueError:
        pass

    progress_raw = payload.get("progress", 0)
    try:
        progress_num = float(progress_raw)
    except (TypeError, ValueError):
        progress_num = 0.0
    # Voicebox may emit 0-100 or 0-1; normalize.
    if progress_num > 1.0:
        progress_num = progress_num / 100.0
    progress_num = max(0.0, min(1.0, progress_num))

    status = str(payload.get("status") or "idle")
    message_raw = payload.get("message")
    message = str(message_raw) if message_raw else None

    known = {"model_name", "status", "progress", "message"}
    extra = {k: v for k, v in payload.items() if k not in known}

    return ModelProgress(
        model_name=str(payload.get("model_name") or model_name),
        status=status,
        progress=progress_num,
        message=message,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _parse_profile(row: dict[str, Any]) -> VoiceboxProfile:
    pid = str(row.get("id") or row.get("profile_id") or "")
    name = str(row.get("name") or row.get("display_name") or "")
    eng_raw = row.get("default_engine") or row.get("engine") or row.get("preset_engine")
    engine = str(eng_raw) if eng_raw else None
    samples_raw = row.get("samples") or []
    samples = (
        [s for s in samples_raw if isinstance(s, dict)]
        if isinstance(samples_raw, list)
        else []
    )
    created = row.get("created_at")
    created_s = str(created) if created else None

    known = {
        "id", "profile_id", "name", "display_name", "default_engine", "engine",
        "preset_engine", "samples", "created_at",
    }
    extra = {k: v for k, v in row.items() if k not in known}

    return VoiceboxProfile(
        id=pid,
        name=name,
        engine=engine,
        samples=samples,
        created_at=created_s,
        extra=extra,
    )


def _parse_sample(row: dict[str, Any], profile_id: str = "") -> VoiceboxSample:
    sid = str(row.get("id") or row.get("sample_id") or "")
    pid = str(row.get("profile_id") or profile_id or "")
    path_raw = row.get("path") or row.get("file_path") or row.get("url")
    path = str(path_raw) if path_raw else None
    label_raw = row.get("label") or row.get("reference_text")
    label = str(label_raw) if label_raw else None
    dur_raw = row.get("duration_ms")
    if dur_raw is None and isinstance(row.get("duration"), (int, float)):
        dur_raw = int(float(row["duration"]) * 1000)
    duration_ms = int(dur_raw) if isinstance(dur_raw, (int, float)) else None

    known = {
        "id", "sample_id", "profile_id", "path", "file_path", "url", "label",
        "reference_text", "duration_ms", "duration",
    }
    extra = {k: v for k, v in row.items() if k not in known}

    return VoiceboxSample(
        id=sid,
        profile_id=pid,
        path=path,
        label=label,
        duration_ms=duration_ms,
        extra=extra,
    )


async def list_profiles() -> list[VoiceboxProfile]:
    """``GET /profiles`` → list of :class:`VoiceboxProfile`."""
    async with _client() as client:
        r = await _do(client.get("/profiles"), op="list_profiles")
    _raise_for_status(r, op="list_profiles")
    payload = r.json()
    if not isinstance(payload, list):
        raise VoiceboxAPIError(
            f"list_profiles: expected list, got {type(payload).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return [_parse_profile(row) for row in payload if isinstance(row, dict)]


async def get_profile(profile_id: str) -> VoiceboxProfile:
    """``GET /profiles/{profile_id}``."""
    async with _client() as client:
        r = await _do(
            client.get(f"/profiles/{profile_id}"),
            op=f"get_profile({profile_id})",
        )
    _raise_for_status(r, op=f"get_profile({profile_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"get_profile: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_profile(row)


async def create_profile(
    name: str,
    *,
    engine: Optional[str] = None,
    description: Optional[str] = None,
    language: str = "en",
    voice_type: Optional[str] = "cloned",
    preset_engine: Optional[str] = None,
    preset_voice_id: Optional[str] = None,
    design_prompt: Optional[str] = None,
) -> VoiceboxProfile:
    """``POST /profiles`` with a JSON ``VoiceProfileCreate`` body.

    Voicebox v0.4.0 no longer accepts a multipart audio upload here —
    samples go through :func:`add_sample_to_profile` after the profile
    exists.
    """
    body: dict[str, Any] = {"name": name, "language": language}
    if description is not None:
        body["description"] = description
    if voice_type is not None:
        body["voice_type"] = voice_type
    if engine is not None:
        body["default_engine"] = engine
    if preset_engine is not None:
        body["preset_engine"] = preset_engine
    if preset_voice_id is not None:
        body["preset_voice_id"] = preset_voice_id
    if design_prompt is not None:
        body["design_prompt"] = design_prompt

    async with _client() as client:
        r = await _do(
            client.post("/profiles", json=body),
            op=f"create_profile({name!r})",
        )
    _raise_for_status(r, op=f"create_profile({name!r})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"create_profile: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_profile(row)


async def update_profile(
    profile_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    language: Optional[str] = None,
    engine: Optional[str] = None,
) -> VoiceboxProfile:
    """``PUT /profiles/{profile_id}``.

    Voicebox requires a full ``VoiceProfileCreate`` body on PUT — so we
    fetch the current profile first and merge the delta.
    """
    current = await get_profile(profile_id)
    body: dict[str, Any] = {
        "name": name if name is not None else current.name,
        "language": language if language is not None else "en",
    }
    if description is not None:
        body["description"] = description
    if engine is not None:
        body["default_engine"] = engine
    elif current.engine is not None:
        body["default_engine"] = current.engine

    async with _client() as client:
        r = await _do(
            client.put(f"/profiles/{profile_id}", json=body),
            op=f"update_profile({profile_id})",
        )
    _raise_for_status(r, op=f"update_profile({profile_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"update_profile: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_profile(row)


async def delete_profile(profile_id: str) -> None:
    """``DELETE /profiles/{profile_id}``.

    404 is treated as success (already gone).
    """
    async with _client() as client:
        r = await _do(
            client.delete(f"/profiles/{profile_id}"),
            op=f"delete_profile({profile_id})",
        )
    if r.status_code == 404:
        return
    _raise_for_status(r, op=f"delete_profile({profile_id})")


async def add_sample_to_profile(
    profile_id: str,
    audio_bytes: bytes,
    *,
    reference_text: str,
    filename: str = "sample.wav",
    content_type: str = "audio/wav",
) -> VoiceboxSample:
    """``POST /profiles/{profile_id}/samples`` (multipart).

    Voicebox v0.4.0 requires ``reference_text`` alongside the audio
    file — it's what the model aligns clone features against.
    """
    files = {"file": (filename, audio_bytes, content_type)}
    data = {"reference_text": reference_text}
    async with _client() as client:
        r = await _do(
            client.post(
                f"/profiles/{profile_id}/samples", data=data, files=files
            ),
            op=f"add_sample_to_profile({profile_id})",
        )
    _raise_for_status(r, op=f"add_sample_to_profile({profile_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"add_sample_to_profile: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_sample(row, profile_id=profile_id)


async def list_preset_voices(engine: str) -> list[PresetVoice]:
    """``GET /profiles/presets/{engine}`` → list of preset voices."""
    async with _client() as client:
        r = await _do(
            client.get(f"/profiles/presets/{engine}"),
            op=f"list_preset_voices({engine})",
        )
    _raise_for_status(r, op=f"list_preset_voices({engine})")
    payload = r.json()
    # Voicebox response: {engine, voices: [...]}
    voices_raw = payload.get("voices") if isinstance(payload, dict) else payload
    if not isinstance(voices_raw, list):
        return []
    out: list[PresetVoice] = []
    for row in voices_raw:
        if not isinstance(row, dict):
            continue
        vid = str(row.get("id") or row.get("voice_id") or row.get("name") or "")
        vname = str(row.get("name") or row.get("display_name") or vid)
        known = {"id", "voice_id", "name", "display_name"}
        extra = {k: v for k, v in row.items() if k not in known}
        out.append(PresetVoice(id=vid, name=vname, engine=engine, extra=extra))
    return out


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _parse_generation_response(row: dict[str, Any]) -> GenerationResponse:
    gid = str(row.get("id") or row.get("generation_id") or "")
    status = str(row.get("status") or "queued")
    known = {"id", "generation_id", "status"}
    extra = {k: v for k, v in row.items() if k not in known}
    return GenerationResponse(generation_id=gid, status=status, extra=extra)


def _parse_generation_status(row: dict[str, Any], generation_id: str = "") -> GenerationStatus:
    gid = str(row.get("id") or row.get("generation_id") or generation_id or "")
    status = str(row.get("status") or "queued")

    progress_raw = row.get("progress", 0)
    try:
        progress_num = float(progress_raw)
    except (TypeError, ValueError):
        progress_num = 0.0
    if progress_num > 1.0:
        progress_num = progress_num / 100.0
    progress_num = max(0.0, min(1.0, progress_num))

    # Voicebox may return "duration" (seconds, float) or "duration_ms".
    dur_ms = row.get("duration_ms")
    if dur_ms is None and isinstance(row.get("duration"), (int, float)):
        dur_ms = int(float(row["duration"]) * 1000)
    duration_ms = int(dur_ms) if isinstance(dur_ms, (int, float)) else None

    err_raw = row.get("error")
    error = str(err_raw) if err_raw else None

    known = {"id", "generation_id", "status", "progress", "duration", "duration_ms", "error"}
    extra = {k: v for k, v in row.items() if k not in known}

    return GenerationStatus(
        generation_id=gid,
        status=status,
        progress=progress_num,
        duration_ms=duration_ms,
        error=error,
        extra=extra,
    )


async def generate(
    *,
    profile_id: str,
    text: str,
    engine: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
) -> GenerationResponse:
    """``POST /generate`` with a ``GenerationRequest`` body.

    Required: ``profile_id``, ``text``. Optional: ``engine`` (default
    Voicebox-side is ``"qwen"``). Anything else — ``seed``,
    ``model_size``, ``instruct``, ``max_chunk_chars``, ``crossfade_ms``,
    ``normalize``, ``effects_chain``, ``language`` — goes through
    ``options``.
    """
    body: dict[str, Any] = {"profile_id": profile_id, "text": text}
    if engine is not None:
        body["engine"] = engine
    if options:
        for k, v in options.items():
            if k in body:
                continue
            body[k] = v

    async with _client() as client:
        r = await _do(
            client.post("/generate", json=body),
            op="generate",
        )
    _raise_for_status(r, op="generate")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"generate: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_generation_response(row)


async def get_generation_status(generation_id: str) -> GenerationStatus:
    """``GET /generate/{generation_id}/status``."""
    async with _client() as client:
        r = await _do(
            client.get(f"/generate/{generation_id}/status"),
            op=f"get_generation_status({generation_id})",
        )
    _raise_for_status(r, op=f"get_generation_status({generation_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"get_generation_status: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_generation_status(row, generation_id=generation_id)


async def cancel_generation(generation_id: str) -> None:
    """``POST /generate/{generation_id}/cancel``."""
    async with _client() as client:
        r = await _do(
            client.post(f"/generate/{generation_id}/cancel"),
            op=f"cancel_generation({generation_id})",
        )
    _raise_for_status(r, op=f"cancel_generation({generation_id})")


async def regenerate(generation_id: str) -> GenerationResponse:
    """``POST /generate/{generation_id}/regenerate``."""
    async with _client() as client:
        r = await _do(
            client.post(f"/generate/{generation_id}/regenerate"),
            op=f"regenerate({generation_id})",
        )
    _raise_for_status(r, op=f"regenerate({generation_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"regenerate: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_generation_response(row)


async def retry_generation(generation_id: str) -> GenerationResponse:
    """``POST /generate/{generation_id}/retry``."""
    async with _client() as client:
        r = await _do(
            client.post(f"/generate/{generation_id}/retry"),
            op=f"retry_generation({generation_id})",
        )
    _raise_for_status(r, op=f"retry_generation({generation_id})")
    row = r.json()
    if not isinstance(row, dict):
        raise VoiceboxAPIError(
            f"retry_generation: expected object, got {type(row).__name__}",
            status_code=r.status_code,
            body=r.text[:300],
        )
    return _parse_generation_response(row)


async def get_generation_audio(generation_id: str) -> tuple[bytes, str]:
    """``GET /audio/{generation_id}`` → ``(audio_bytes, content_type)``."""
    async with _client() as client:
        r = await _do(
            client.get(f"/audio/{generation_id}"),
            op=f"get_generation_audio({generation_id})",
        )
    _raise_for_status(r, op=f"get_generation_audio({generation_id})")
    content_type = r.headers.get("content-type") or "application/octet-stream"
    return r.content, content_type


# ---------------------------------------------------------------------------
# High-level: generate + poll + download
# ---------------------------------------------------------------------------


_TERMINAL_OK = {"complete", "completed", "done", "success", "succeeded"}
_TERMINAL_FAIL = {"failed", "error", "errored"}
_TERMINAL_CANCELLED = {"cancelled", "canceled"}


async def _await_and_download(
    generation_id: str,
    *,
    poll_interval: float = 0.5,
    timeout: Optional[float] = None,
) -> tuple[bytes, Optional[int], str, Optional[str]]:
    """Poll ``generation_id`` until terminal, then download audio.

    Shared by :func:`generate_and_wait`, :func:`regenerate_and_wait`,
    and :func:`retry_and_wait`. Returns
    ``(audio_bytes, duration_ms, generation_id, content_type)``.

    Raises :class:`VoiceboxGenerationError` on ``status=failed`` /
    cancelled, and :class:`VoiceboxTimeoutError` when ``timeout``
    elapses before a terminal state. On timeout the generation remains
    on Voicebox so the caller can retry / poll later.
    """
    if not generation_id:
        raise VoiceboxAPIError(
            f"_await_and_download called with empty generation_id",
            status_code=0,
            body="",
        )
    if timeout is None:
        timeout = float(get_settings().voicebox_generation_timeout_seconds)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + float(timeout)

    # First status snapshot — may already be terminal for short inputs.
    last = await get_generation_status(generation_id)

    while True:
        st = last.status.lower()
        if st in _TERMINAL_OK:
            break
        if st in _TERMINAL_FAIL:
            raise VoiceboxGenerationError(
                f"generation {generation_id} failed: {last.error or '<no error message>'}"
            )
        if st in _TERMINAL_CANCELLED:
            raise VoiceboxGenerationError(
                f"generation {generation_id} was cancelled"
            )

        if loop.time() >= deadline:
            raise VoiceboxTimeoutError(
                f"generation {generation_id} did not complete within {timeout:.1f}s"
            )

        await asyncio.sleep(max(0.05, poll_interval))
        last = await get_generation_status(generation_id)

    audio_bytes, content_type = await get_generation_audio(generation_id)
    return audio_bytes, last.duration_ms, generation_id, content_type


async def generate_and_wait(
    *,
    profile_id: str,
    text: str,
    engine: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    poll_interval: float = 0.5,
    timeout: Optional[float] = None,
) -> tuple[bytes, Optional[int], str, Optional[str]]:
    """Kick off a generation, poll until terminal, then fetch audio.

    Returns ``(audio_bytes, duration_ms, generation_id, content_type)``.

    Raises :class:`VoiceboxGenerationError` on ``status=failed``, and
    :class:`VoiceboxTimeoutError` when ``timeout`` elapses before a
    terminal state. On timeout the generation remains on Voicebox so
    the caller can retry / poll later.
    """
    started = await generate(
        profile_id=profile_id, text=text, engine=engine, options=options
    )
    generation_id = started.generation_id
    if not generation_id:
        raise VoiceboxAPIError(
            f"generate returned no id: {started!r}",
            status_code=0,
            body=repr(started),
        )
    return await _await_and_download(
        generation_id, poll_interval=poll_interval, timeout=timeout
    )


async def regenerate_and_wait(
    generation_id: str,
    *,
    poll_interval: float = 0.5,
    timeout: Optional[float] = None,
) -> tuple[bytes, Optional[int], str, Optional[str]]:
    """POST ``/generate/{id}/regenerate`` then await completion + download.

    Returns the same shape as :func:`generate_and_wait`. The returned
    generation_id may be the same as the input (Voicebox reuses the id
    for the new attempt) or a new one — callers should use whatever
    Voicebox reports.
    """
    started = await regenerate(generation_id)
    new_gid = started.generation_id or generation_id
    return await _await_and_download(
        new_gid, poll_interval=poll_interval, timeout=timeout
    )


async def retry_and_wait(
    generation_id: str,
    *,
    poll_interval: float = 0.5,
    timeout: Optional[float] = None,
) -> tuple[bytes, Optional[int], str, Optional[str]]:
    """POST ``/generate/{id}/retry`` then await completion + download.

    Intended for resuming a prior attempt that failed on the Voicebox
    side (e.g., transient model hiccup). Returns the same shape as
    :func:`generate_and_wait`.
    """
    started = await retry_generation(generation_id)
    new_gid = started.generation_id or generation_id
    return await _await_and_download(
        new_gid, poll_interval=poll_interval, timeout=timeout
    )


# ---------------------------------------------------------------------------
# Legacy shims — delete in Commit 4
# ---------------------------------------------------------------------------


async def probe(
    settings: Any = None, *, timeout_s: float = 1.5
) -> VoiceboxStatus:
    """Legacy Phase-2 probe used in ``backend/main.py`` lifespan.

    Delegates to :func:`health_check` and flattens the result to the old
    :class:`VoiceboxStatus` shape. Never raises.
    """
    del settings  # new probe reads from config store, not Settings
    try:
        h = await health_check(timeout=timeout_s)
    except VoiceboxNotConfigured:
        return VoiceboxStatus(
            enabled=False,
            reachable=None,
            base_url="",
            note="Voicebox URL not set — configure in Settings > Voicebox.",
        )
    if not h.enabled:
        return VoiceboxStatus(
            enabled=False,
            reachable=None,
            base_url=h.base_url,
            note="Voicebox disabled — enable in Settings > Voicebox.",
        )
    if h.reachable:
        return VoiceboxStatus(
            enabled=True,
            reachable=True,
            base_url=h.base_url,
            note="Voicebox reachable.",
        )
    return VoiceboxStatus(
        enabled=True,
        reachable=False,
        base_url=h.base_url,
        note=(
            f"Voicebox enabled but unreachable at {h.base_url}: "
            f"{h.error or 'unknown error'}"
        ),
    )


async def synthesize(
    profile_id: str,
    text: str,
    *,
    options: Optional[SynthesisOptions] = None,
) -> SynthesisResult:
    """Legacy Phase-5 wrapper used by ``backend/audio/generation.py``.

    Thin adapter over :func:`generate_and_wait`. Commit 4 will rewrite
    ``generation.py`` to call :func:`generate_and_wait` directly and we
    can then delete this shim.
    """
    opts = options or SynthesisOptions()
    api_options: dict[str, Any] = {}
    if opts.seed is not None:
        api_options["seed"] = opts.seed
    if opts.extra:
        for k, v in opts.extra.items():
            api_options.setdefault(k, v)

    audio_bytes, duration_ms, _gen_id, content_type = await generate_and_wait(
        profile_id=profile_id,
        text=text,
        engine=opts.engine,
        options=api_options or None,
    )
    return SynthesisResult(
        audio_bytes=audio_bytes,
        duration_ms=duration_ms,
        sample_rate=opts.sample_rate,
        content_type=content_type,
    )


# ---------------------------------------------------------------------------
# Legacy VoiceboxClient class (minimal surface — used only by tests, if any)
# ---------------------------------------------------------------------------


class VoiceboxClient:
    """Legacy Phase-2 wrapper — preserved for import compatibility.

    New code should call the module-level functions above directly.
    """

    def __init__(self, settings: Any = None) -> None:  # noqa: ARG002
        # Settings is ignored — we read from the config store per-call.
        pass

    async def list_profiles(self) -> list[dict[str, Any]]:
        return [
            {"id": p.id, "name": p.name, "engine": p.engine, **p.extra}
            for p in await list_profiles()
        ]

    async def generate(
        self,
        *,
        text: str,
        profile_id: str,
        engine: Optional[str] = None,
        effects: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        resp = await generate(
            profile_id=profile_id,
            text=text,
            engine=engine,
            options=effects,
        )
        return {
            "generation_id": resp.generation_id,
            "id": resp.generation_id,
            "status": resp.status,
            **resp.extra,
        }

    async def get_generation(self, generation_id: str) -> dict[str, Any]:
        st = await get_generation_status(generation_id)
        return {
            "generation_id": st.generation_id,
            "status": st.status,
            "progress": st.progress,
            "duration_ms": st.duration_ms,
            "error": st.error,
            **st.extra,
        }

    async def download_generation_audio(self, generation_id: str) -> bytes:
        audio, _ = await get_generation_audio(generation_id)
        return audio

    async def download_generation_audio_with_headers(
        self, generation_id: str
    ) -> tuple[bytes, Optional[str]]:
        audio, ct = await get_generation_audio(generation_id)
        return audio, ct
