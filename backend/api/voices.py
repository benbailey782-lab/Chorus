"""Voice library HTTP API (§7 + §16).

Phase 2 runs in Voicebox-stub mode: metadata and reference-audio upload work
end-to-end, but actual clone-profile creation and TTS preview are gated behind
``VOICEBOX_ENABLED``. See ``backend/voices/voicebox_client.py`` for the stubbed
call-sites and ``docs/VOICEBOX-WIRING.md`` for the per-call wiring checklist.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from backend.config import get_settings
from backend.schemas import (
    Gender,
    Pool,
    VoiceCreate,
    VoiceOut,
    VoicePoolCounts,
    VoiceUpdate,
    VoiceboxStatusOut,
)
from backend.voices import library
from backend.voices.voicebox_client import probe

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
        }
    )


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


@router.get("/voicebox/status", response_model=VoiceboxStatusOut)
async def voicebox_status() -> VoiceboxStatusOut:
    status = await probe()
    return VoiceboxStatusOut(
        enabled=status.enabled,
        reachable=status.reachable,
        base_url=status.base_url,
        note=status.note,
    )


@router.post("", response_model=VoiceOut, status_code=201)
async def create_voice(
    voice_json: str = Form(..., description="JSON-encoded VoiceCreate body"),
    audio: Optional[UploadFile] = File(default=None),
) -> VoiceOut:
    """Create a new voice. Audio is optional (adjustment B).

    Multipart fields:
      * ``voice_json`` — JSON string matching :class:`VoiceCreate`
      * ``audio`` — optional audio file (wav/mp3/m4a/flac/ogg, ≤ configured cap)

    voicebox_profile_id is always null at create time in stub mode
    (adjustment A); wiring is tracked in docs/VOICEBOX-WIRING.md.
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

    # TODO(voicebox): if settings.voicebox_enabled and audio is present,
    #   call VoiceboxClient.create_profile(...) here and persist the returned
    #   id onto voicebox_profile_id. See docs/VOICEBOX-WIRING.md.

    return _voice_to_out(voice)


@router.get("/{voice_id}", response_model=VoiceOut)
def get_voice(voice_id: str) -> VoiceOut:
    return _voice_to_out(_require_voice(voice_id))


@router.patch("/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate) -> VoiceOut:
    _require_voice(voice_id)
    # Pydantic v2: exclude_unset so PATCH semantics survive; by_alias so the
    # aliased field (register_ → "register") matches library column names.
    patch = body.model_dump(exclude_unset=True, by_alias=True)
    voice = library.update_voice(voice_id, patch)
    if voice is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")
    return _voice_to_out(voice)


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str) -> Response:
    ok = library.delete_voice(voice_id)
    if not ok:
        raise HTTPException(404, f"voice {voice_id!r} not found")
    return Response(status_code=204)


@router.post("/{voice_id}/sample", response_model=VoiceOut)
async def replace_sample(voice_id: str, audio: UploadFile = File(...)) -> VoiceOut:
    """Replace (or add) the reference audio for an existing voice."""
    _require_voice(voice_id)
    path = await _save_audio_upload(voice_id, audio)
    voice = library.update_voice(voice_id, {"sample_audio_path": path})
    if voice is None:
        raise HTTPException(404, f"voice {voice_id!r} not found")

    # TODO(voicebox): if settings.voicebox_enabled, call
    #   VoiceboxClient.create_profile(...) with the new audio and update
    #   voicebox_profile_id. See docs/VOICEBOX-WIRING.md.

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
