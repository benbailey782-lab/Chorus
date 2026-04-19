"""Voice library HTTP API (§7 + §16).

Phase 5 remediation Commit 5: POST /api/voices + the new
``sync-to-voicebox`` endpoint do eager Voicebox profile creation when
Voicebox is configured + reachable + a sample is present. PATCH handles
engine and sample changes by delete+recreate for now (multi-sample UI
lands later). DELETE cleans up the Voicebox profile best-effort.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from backend.config import get_settings
from backend.schemas import (
    Gender,
    Pool,
    VoiceCreate,
    VoiceCreateResponse,
    VoiceOut,
    VoicePoolCounts,
    VoiceUpdate,
)
from backend.voices import library, voicebox_client
from backend.voices.voicebox_client import (
    VoiceboxError,
    VoiceboxNotConfigured,
    VoiceboxNotEnabled,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voices", tags=["voices"])

ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
# Loose content-type whitelist — browsers are inconsistent; extension is the
# primary gate and matches what the upload field accepts.
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/mp4", "audio/x-m4a", "audio/aac",
    "audio/flac", "audio/x-flac",
    "audio/ogg", "audio/vorbis",
    "application/octet-stream",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _voice_to_out(voice: dict) -> VoiceOut:
    return VoiceOut.model_validate(
        {
            "id": voice["id"],
            "voicebox_profile_id": voice["voicebox_profile_id"],
            "display_name": voice["display_name"],
            "gender": voice.get("gender"),
            "age_range": voice.get("age_range"),
            "accent": voice.get("accent"),
            "tone": voice.get("tone", []),
            "timbre": voice.get("timbre"),
            "pace": voice.get("pace"),
            "register": voice.get("register"),  # wire name via alias
            "character_archetypes": voice.get("character_archetypes", []),
            "pool": voice["pool"],
            "engine_preference": voice.get("engine_preference"),
            "sample_text": voice.get("sample_text"),
            "source_notes": voice.get("source_notes"),
            "tags": voice.get("tags", []),
            "sample_audio_path": voice.get("sample_audio_path"),
            "has_sample_audio": bool(
                voice.get("sample_audio_path")
                and Path(voice["sample_audio_path"]).exists()
            ),
            "times_used": voice.get("times_used", 0),
            "added_at": voice["added_at"],
            "updated_at": voice["updated_at"],
            # Phase 5 remediation: always present on v8+ DBs, defaulted in
            # library._row_to_voice for forward-compat.
            "voicebox_engine": voice.get("voicebox_engine") or "qwen3-tts",
            "voicebox_effect_preset_id": voice.get("voicebox_effect_preset_id"),
        }
    )


async def _sync_voice_to_voicebox(voice: dict) -> tuple[Optional[str], Optional[str]]:
    """Best-effort: create a Voicebox profile + attach the sample.

    Returns ``(profile_id, error)``. On any failure (not configured,
    disabled, unreachable, API error), ``profile_id`` is None and
    ``error`` is a human-readable explanation.
    """
    sample = voice.get("sample_audio_path")
    if not sample:
        return None, None  # no sample = nothing to sync, not an error
    sample_path = Path(sample)
    if not sample_path.exists():
        return None, f"sample file missing on disk: {sample}"

    try:
        audio_bytes = sample_path.read_bytes()
    except OSError as e:
        return None, f"could not read sample file: {e}"

    engine = voice.get("voicebox_engine") or "qwen3-tts"
    # Voicebox requires reference_text for each sample upload — we don't
    # have transcripts for reference clips, so fall back to sample_text (a
    # preview line the user may have set) or a generic placeholder.
    ref_text = (voice.get("sample_text") or "").strip() or "Sample reference"

    try:
        profile = await voicebox_client.create_profile(
            name=voice["display_name"],
            engine=engine,
        )
    except VoiceboxNotConfigured:
        return None, "Voicebox URL is not configured."
    except VoiceboxNotEnabled:
        return None, "Voicebox is disabled in Settings."
    except VoiceboxError as e:
        log.warning(
            "voicebox_sync: create_profile failed for voice %s: %s",
            voice["id"], e,
        )
        return None, f"create_profile failed: {e}"

    try:
        sample_resp = await voicebox_client.add_sample_to_profile(
            profile.id,
            audio_bytes,
            reference_text=ref_text,
            filename=sample_path.name,
        )
    except VoiceboxError as e:
        # Profile created but sample failed — roll back the orphan profile
        # so next retry starts clean.
        log.warning(
            "voicebox_sync: add_sample failed for voice %s profile %s: %s; rolling back",
            voice["id"], profile.id, e,
        )
        try:
            await voicebox_client.delete_profile(profile.id)
        except VoiceboxError:
            pass
        return None, f"add_sample failed: {e}"

    # Persist voicebox_profile_id on the voice and a voice_samples row.
    library.update_voice(voice["id"], {"voicebox_profile_id": profile.id})
    try:
        library.add_voice_sample(
            voice["id"],
            str(sample_path),
            label="Original",
            voicebox_sample_id=sample_resp.id,
            duration_ms=sample_resp.duration_ms,
        )
    except Exception as e:  # noqa: BLE001 — never block on sidecar table
        log.warning("voicebox_sync: voice_samples upsert failed: %s", e)

    return profile.id, None


def _require_voice(voice_id: str) -> dict:
    voice = library.get_voice(voice_id)
    if voice is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")
    return voice


async def _save_audio_upload(voice_id: str, upload: UploadFile) -> str:
    """Stream an UploadFile to ``data/voice_library/samples/<voice_id>.<ext>``.

    Enforces extension whitelist and the configured size cap. Returns the
    absolute path as a string for persistence on the voices row.
    """
    filename = upload.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            400,
            f"unsupported audio format {ext!r}; allowed: {sorted(ALLOWED_AUDIO_EXTS)}",
        )
    if upload.content_type and upload.content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        # Don't hard-fail on Content-Type — browsers lie. Log for debugging.
        log.info("voice sample upload content-type %r (accepting)", upload.content_type)

    settings = get_settings()
    max_bytes = settings.max_voice_sample_bytes
    dest = library.sample_path_for(voice_id, ext)
    # Remove any pre-existing sample for this voice (covers replacement case).
    for existing in library.samples_dir().glob(f"{voice_id}.*"):
        try:
            existing.unlink()
        except OSError:
            pass

    written = 0
    chunk_size = 1 << 20  # 1 MB
    with dest.open("wb") as fh:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    413,
                    f"audio file exceeds {settings.max_voice_sample_mb} MB limit",
                )
            fh.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "audio file was empty")
    return str(dest)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[VoiceOut])
def list_voices(
    pool: Optional[Pool] = Query(default=None),
    gender: Optional[Gender] = Query(default=None),
    q: Optional[str] = Query(default=None, description="search display_name, tags, tone, accent, character_archetypes"),
) -> list[VoiceOut]:
    voices = library.list_voices(pool=pool, gender=gender, q=q)
    return [_voice_to_out(v) for v in voices]


@router.get("/pools/summary", response_model=VoicePoolCounts)
def pool_summary() -> VoicePoolCounts:
    counts = library.count_by_pool()
    return VoicePoolCounts(**counts)


@router.get("/voicebox/status", deprecated=True, include_in_schema=False)
async def voicebox_status_legacy() -> RedirectResponse:
    """Deprecated — redirects to the canonical /api/voicebox/status (Phase 5).

    Kept for backwards compatibility with pre-Phase-5 clients; HTTP 308 so
    the method and body are preserved if a future client sends one.
    """
    return RedirectResponse(url="/api/voicebox/status", status_code=308)


@router.post("", response_model=VoiceCreateResponse, status_code=201)
async def create_voice(
    voice_json: str = Form(..., description="JSON-encoded VoiceCreate body"),
    audio: Optional[UploadFile] = File(default=None),
) -> VoiceCreateResponse:
    """Create a new voice. Audio is optional.

    Multipart fields:
      * ``voice_json`` — JSON string matching :class:`VoiceCreate`
      * ``audio`` — optional audio file (wav/mp3/m4a/flac/ogg, ≤ configured cap)

    Phase-5R: when a sample is provided AND Voicebox is configured +
    enabled + reachable, we eagerly create a Voicebox profile and
    persist the returned ``voicebox_profile_id``. On any sync failure
    the voice is still saved and the response carries a non-null
    ``voicebox_sync_error`` so the UI can prompt a later retry via
    ``POST /api/voices/{id}/sync-to-voicebox``.
    """
    try:
        payload_raw = json.loads(voice_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"voice_json is not valid JSON: {e}") from e
    try:
        payload = VoiceCreate.model_validate(payload_raw)
    except Exception as e:  # noqa: BLE001 — surface validation errors
        raise HTTPException(422, f"voice_json failed validation: {e}") from e

    voice = library.create_voice(payload.model_dump(by_alias=True))

    if audio is not None and audio.filename:
        try:
            path = await _save_audio_upload(voice["id"], audio)
        except HTTPException:
            # Roll back the DB row if audio save failed — keeps library clean.
            library.delete_voice(voice["id"])
            raise
        voice = library.update_voice(voice["id"], {"sample_audio_path": path}) or voice

    # Eager Voicebox profile creation (best-effort). Silently skipped when
    # no sample is attached — the UI will surface "Needs sync" once a
    # sample lands via the separate /sample endpoint.
    sync_error: Optional[str] = None
    if voice.get("sample_audio_path"):
        _profile_id, sync_error = await _sync_voice_to_voicebox(voice)
        if _profile_id:
            voice = library.get_voice(voice["id"]) or voice

    return VoiceCreateResponse(
        voice=_voice_to_out(voice),
        voicebox_sync_error=sync_error,
    )


@router.get("/{voice_id}", response_model=VoiceOut)
def get_voice(voice_id: str) -> VoiceOut:
    return _voice_to_out(_require_voice(voice_id))


@router.patch("/{voice_id}", response_model=VoiceOut)
async def update_voice(voice_id: str, body: VoiceUpdate) -> VoiceOut:
    existing = _require_voice(voice_id)
    # Pydantic v2: exclude_unset so PATCH semantics survive; by_alias so the
    # aliased field (register_ → "register") matches library column names.
    patch = body.model_dump(exclude_unset=True, by_alias=True)

    # Phase-5R: engine change requires rebuilding the Voicebox profile
    # because a profile's samples are bound to the engine that created
    # them. Simpler in this commit to delete+recreate than to reshape
    # live samples. Non-engine / non-sample edits update in-place.
    engine_changed = (
        "voicebox_engine" in patch
        and patch["voicebox_engine"] != existing.get("voicebox_engine")
    )
    old_profile_id = existing.get("voicebox_profile_id")

    voice = library.update_voice(voice_id, patch)
    if voice is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")

    if engine_changed and old_profile_id:
        log.info(
            "voicebox_sync: engine change on voice %s (%s → %s); "
            "delete+recreate profile %s",
            voice_id,
            existing.get("voicebox_engine"),
            patch["voicebox_engine"],
            old_profile_id,
        )
        try:
            await voicebox_client.delete_profile(old_profile_id)
        except VoiceboxError as e:
            log.warning(
                "voicebox_sync: delete_profile(%s) failed (continuing): %s",
                old_profile_id, e,
            )
        # Clear the old id so the re-sync persists a fresh one on success.
        voice = library.update_voice(voice_id, {"voicebox_profile_id": None}) or voice
        if voice.get("sample_audio_path"):
            _new_id, err = await _sync_voice_to_voicebox(voice)
            if err:
                log.warning(
                    "voicebox_sync: rebuild failed for voice %s: %s", voice_id, err
                )
            voice = library.get_voice(voice_id) or voice

    return _voice_to_out(voice)


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: str) -> Response:
    existing = library.get_voice(voice_id)
    if existing is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")

    profile_id = existing.get("voicebox_profile_id")
    if profile_id:
        # Best-effort cleanup; 404 from Voicebox is treated as success
        # inside the client. Unreachability is logged and ignored so a
        # Voicebox outage doesn't block DB cleanup.
        try:
            await voicebox_client.delete_profile(profile_id)
        except VoiceboxError as e:
            log.warning(
                "voicebox_sync: delete_profile(%s) on voice %s failed (continuing): %s",
                profile_id, voice_id, e,
            )

    ok = library.delete_voice(voice_id)
    if not ok:
        raise HTTPException(404, f"voice {voice_id!r} not found")
    return Response(status_code=204)


@router.post("/{voice_id}/sync-to-voicebox", response_model=VoiceCreateResponse)
async def sync_voice_to_voicebox(voice_id: str) -> VoiceCreateResponse:
    """Phase-5R: re-attempt eager Voicebox profile creation.

    Used by the library UI when a voice's ``voicebox_profile_id`` is null
    (e.g., the initial eager sync failed or Voicebox wasn't reachable at
    create time). If a profile already exists, short-circuits with a
    successful response (no sync_error).
    """
    voice = _require_voice(voice_id)
    if voice.get("voicebox_profile_id"):
        return VoiceCreateResponse(voice=_voice_to_out(voice), voicebox_sync_error=None)

    if not voice.get("sample_audio_path"):
        return VoiceCreateResponse(
            voice=_voice_to_out(voice),
            voicebox_sync_error=(
                "This voice has no reference audio yet — upload a sample "
                "before syncing."
            ),
        )

    _profile_id, err = await _sync_voice_to_voicebox(voice)
    refreshed = library.get_voice(voice_id) or voice
    return VoiceCreateResponse(
        voice=_voice_to_out(refreshed),
        voicebox_sync_error=err,
    )


@router.post("/{voice_id}/sample", response_model=VoiceOut)
async def replace_sample(voice_id: str, audio: UploadFile = File(...)) -> VoiceOut:
    """Replace (or add) the reference audio for an existing voice.

    Phase-5R: the new sample triggers a Voicebox profile rebuild. Simpler
    than managing multi-sample diffs — delete the old profile, create a
    fresh one, attach the new sample. Best-effort on failure.
    """
    existing = _require_voice(voice_id)
    path = await _save_audio_upload(voice_id, audio)
    voice = library.update_voice(voice_id, {"sample_audio_path": path})
    if voice is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")

    old_profile_id = existing.get("voicebox_profile_id")
    if old_profile_id:
        try:
            await voicebox_client.delete_profile(old_profile_id)
        except VoiceboxError as e:
            log.warning(
                "voicebox_sync: delete_profile(%s) on sample replace failed: %s",
                old_profile_id, e,
            )
        voice = library.update_voice(voice_id, {"voicebox_profile_id": None}) or voice

    _new_id, err = await _sync_voice_to_voicebox(voice)
    if err:
        log.info(
            "voicebox_sync: replace-sample sync error on voice %s: %s",
            voice_id, err,
        )
    voice = library.get_voice(voice_id) or voice

    return _voice_to_out(voice)


@router.delete("/{voice_id}/sample", response_model=VoiceOut)
def delete_sample(voice_id: str) -> VoiceOut:
    voice = _require_voice(voice_id)
    sample = voice.get("sample_audio_path")
    if sample:
        try:
            Path(sample).unlink(missing_ok=True)
        except OSError:
            pass
    updated = library.update_voice(voice_id, {"sample_audio_path": None})
    return _voice_to_out(updated or voice)


@router.get("/{voice_id}/sample")
def download_sample(voice_id: str) -> FileResponse:
    """Stream the stored reference audio for in-browser playback.

    With Voicebox disabled this is the "preview" endpoint — it plays the
    user-uploaded clip directly. When Voicebox is wired up, a separate
    ``POST /api/voices/{id}/preview`` will generate a clip of ``sample_text``
    spoken in the cloned voice.
    """
    voice = _require_voice(voice_id)
    sample = voice.get("sample_audio_path")
    if not sample or not Path(sample).exists():
        raise HTTPException(404, "no sample audio for this voice")
    path = Path(sample)
    # Infer media type from extension; fall back to application/octet-stream.
    media = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)
