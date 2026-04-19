from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ProjectStatus = Literal[
    "ingesting", "casting", "attributing", "attributed",
    "generating", "assembling", "complete", "error"
]

# §6 render-mode vocabulary. Matches the CHECK constraint on segments.render_mode.
RenderMode = Literal[
    "prose", "dialogue", "epigraph", "letter", "poetry",
    "song_lyrics", "emphasis", "thought", "chapter_heading",
]
ProjectMode = Literal["automated", "director"]
ChapterStatus = Literal["pending", "attributed", "generated", "assembled"]

# --- Voice library enums (§7.2) ---------------------------------------------
# Kept as Literal so FastAPI auto-validates + docs list valid values, and
# mirrored in frontend/src/lib/constants.ts.
Gender = Literal["male", "female", "nonbinary", "unknown"]
AgeRange = Literal["child", "teen", "young_adult", "middle_aged", "elder", "unknown"]
Pool = Literal["narrator", "main", "background"]
Timbre = Literal["light", "medium", "deep", "unknown"]
Pace = Literal["slow", "measured", "quick", "unknown"]
Register = Literal["formal", "casual", "rough", "warm", "unknown"]
EnginePreference = Literal[
    "auto", "chatterbox_turbo", "qwen3_tts", "humeai_tada", "luxtts", "unknown"
]

# Phase 5 remediation — Voicebox v0.4.0's 7 TTS engines. Mirrored in the fresh
# CHECK constraint on voices.voicebox_engine in SCHEMA_SQL and enforced at the
# application layer for DBs upgraded via the v7→v8 migration (SQLite can't ADD
# COLUMN with a CHECK). Distinct from ``EnginePreference`` (used for the older
# `engine_preference` column with its own vocabulary) — kept separate so we
# don't retroactively break Phase 2/3 data.
VoiceboxEngine = Literal[
    "qwen3-tts",
    "luxtts",
    "chatterbox-multilingual",
    "chatterbox-turbo",
    "humeai-tada",
    "kokoro-82m",
    "qwen-custom-voice",
]


class ProjectCreate(BaseModel):
    title: str
    author: Optional[str] = None
    language: str = "en"
    mode: ProjectMode = "automated"


class ProjectOut(BaseModel):
    id: str
    slug: str
    title: str
    author: Optional[str] = None
    language: str
    status: ProjectStatus
    mode: ProjectMode
    pov_narrator_enabled: bool
    ambient_enabled: bool
    cover_art_path: Optional[str] = None
    source_path: Optional[str] = None
    total_duration_ms: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    actual_cost_usd: Optional[float] = None
    chapter_count: int = 0
    created_at: str
    updated_at: str


class ChapterOut(BaseModel):
    id: str
    project_id: str
    number: int
    title: Optional[str] = None
    word_count: Optional[int] = None
    estimated_duration_ms: Optional[int] = None
    status: ChapterStatus
    pov_character_id: Optional[str] = None
    ambient_scene_tag: Optional[str] = None
    segment_count: int = 0


class ChapterDetail(ChapterOut):
    raw_text: str


class IngestResult(BaseModel):
    project_id: str
    source_kind: Literal["txt", "epub"]
    title: Optional[str] = None
    author: Optional[str] = None
    chapters_detected: int
    chapters: list[ChapterOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    db: Literal["ok", "error"]


# --- Voice library (§7.2) ---------------------------------------------------

class VoiceBase(BaseModel):
    """Fields shared by create and out. Arrays default to empty lists.

    ``register_`` uses a trailing-underscore Python name because ``register``
    collides with a method inherited on Pydantic's ModelMetaclass via
    ABCMeta.register; aliased to ``register`` on the wire so the JSON shape
    still matches §7.2 exactly.
    """
    model_config = ConfigDict(populate_by_name=True)

    display_name: str = Field(min_length=1, max_length=200)
    gender: Optional[Gender] = None
    age_range: Optional[AgeRange] = None
    accent: Optional[str] = None
    tone: list[str] = Field(default_factory=list)
    timbre: Optional[Timbre] = None
    pace: Optional[Pace] = None
    register_: Optional[Register] = Field(default=None, alias="register", serialization_alias="register")
    character_archetypes: list[str] = Field(default_factory=list)
    pool: Pool
    engine_preference: Optional[EnginePreference] = None
    sample_text: Optional[str] = None
    source_notes: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    # Phase 5 remediation: per-voice TTS engine + effect preset. The CHECK
    # constraint in SCHEMA_SQL covers fresh DBs; the Literal type enforces
    # the allowed set on DBs upgraded via the v7→v8 migration.
    voicebox_engine: VoiceboxEngine = "qwen3-tts"
    voicebox_effect_preset_id: Optional[str] = None


class VoiceCreate(VoiceBase):
    """POST /api/voices payload. Audio upload is OPTIONAL (adjustment B) — the
    audio file (if any) is sent as a separate multipart field and attached
    after metadata validation."""


class VoiceUpdate(BaseModel):
    """PATCH /api/voices/{id}. All fields optional; unset = unchanged."""
    model_config = ConfigDict(populate_by_name=True)

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    gender: Optional[Gender] = None
    age_range: Optional[AgeRange] = None
    accent: Optional[str] = None
    tone: Optional[list[str]] = None
    timbre: Optional[Timbre] = None
    pace: Optional[Pace] = None
    register_: Optional[Register] = Field(default=None, alias="register", serialization_alias="register")
    character_archetypes: Optional[list[str]] = None
    pool: Optional[Pool] = None
    engine_preference: Optional[EnginePreference] = None
    sample_text: Optional[str] = None
    source_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    # Phase 5 remediation — both fully optional here (unset = unchanged).
    voicebox_engine: Optional[VoiceboxEngine] = None
    voicebox_effect_preset_id: Optional[str] = None


class VoiceOut(VoiceBase):
    id: str
    voicebox_profile_id: Optional[str] = None  # Adjustment A — always null in Phase 2
    sample_audio_path: Optional[str] = None
    has_sample_audio: bool = False
    times_used: int = 0
    added_at: str
    updated_at: str


class VoiceCreateResponse(BaseModel):
    """Phase 5 remediation — POST /api/voices wraps the saved Voice with a
    best-effort Voicebox sync error.

    The voice row is always persisted; ``voicebox_sync_error`` is populated
    when eager profile creation failed (Voicebox unreachable, no sample,
    flag off, etc.). The UI surfaces it as a banner and offers a manual
    "Sync to Voicebox" retry from the library.
    """
    voice: VoiceOut
    voicebox_sync_error: Optional[str] = None


class VoiceSampleOut(BaseModel):
    """Phase 5 remediation — one row per entry in the new voice_samples table.

    ``voicebox_sample_id`` is populated once the sample has been synced with a
    Voicebox profile (via POST /profiles/{id}/samples); null until then.
    Backfilled rows from the v7→v8 migration carry ``label='Original'``.
    """
    id: str
    voice_id: str
    sample_path: str
    voicebox_sample_id: Optional[str] = None
    label: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: str


class VoicePoolCounts(BaseModel):
    narrator: int = 0
    main: int = 0
    background: int = 0


class VoiceboxStatusOut(BaseModel):
    """GET /api/voices/voicebox/status — surfaced to the UI so it can hide or
    disable generation-dependent controls without making the user guess.

    Deprecated in Phase 5 — kept for backwards compat. The canonical endpoint
    is now ``GET /api/voicebox/status`` returning :class:`VoiceboxHealthOut`.
    """
    enabled: bool
    reachable: Optional[bool] = None  # null when disabled
    base_url: str
    note: str


class VoiceboxHealthOut(BaseModel):
    """GET /api/voicebox/status — richer Phase-5 shape with version,
    profile count, and available engines.

    Phase-5-remediation additions:
      * ``configured`` — ``bool(base_url.strip())``. The UI uses this to
        distinguish "no URL saved yet" from "URL saved but disabled".
      * ``model_loaded`` — mirrors Voicebox ``/health``'s field so the
        Settings UI can surface whether Voicebox has loaded a TTS model.

    ``error`` is populated when enabled=True but reachable=False.
    """
    configured: bool = False
    enabled: bool
    reachable: bool
    base_url: str
    version: Optional[str] = None
    profile_count: Optional[int] = None
    available_engines: list[str] = Field(default_factory=list)
    model_loaded: bool = False
    error: Optional[str] = None


class VoiceboxTestConnectionRequest(BaseModel):
    """POST /api/voicebox/test-connection payload.

    The UI uses this to probe an arbitrary URL without writing it to
    config. ``url`` is whatever the user has typed into the URL input.
    """
    url: str


class VoiceboxTestConnectionResponse(BaseModel):
    """Response for POST /api/voicebox/test-connection.

    Shape mirrors Voicebox's own ``/health`` response so the UI can render
    "Reachable · version X · GPU: yes · Model loaded: yes · N profiles"
    straight from this object.
    """
    reachable: bool
    version: Optional[str] = None
    models_loaded: int = 0
    gpu_available: bool = False
    model_loaded: bool = False
    profile_count: int = 0
    error: Optional[str] = None


class VoiceboxConfigUpdate(BaseModel):
    """PATCH /api/voicebox/config body. Either/both fields optional.

    ``base_url=""`` is a valid value — it clears a previously-saved URL
    (and forces ``enabled`` to False, since you can't enable without a
    URL).
    """
    base_url: Optional[str] = None
    enabled: Optional[bool] = None


class VoiceboxConfigOut(BaseModel):
    """Response shape for PATCH /api/voicebox/config — the new effective
    state after applying the update."""
    base_url: str
    enabled: bool
    configured: bool


class ModelStatusOut(BaseModel):
    """GET /api/voicebox/models row. Mirrors
    :class:`backend.voices.voicebox_client.ModelStatus` but stripped to the
    fields the UI needs (display_name, size_mb, hf_repo_id are not
    surfaced yet — add them if the Voicebox admin UI is ever implemented
    in Chorus)."""
    name: str
    loaded: bool
    downloaded: bool
    status: Optional[str] = None


class ModelProgressOut(BaseModel):
    """GET /api/voicebox/models/{model_name}/progress.

    ``status`` is one of ``loading|downloading|complete|loaded|error|idle``
    as surfaced by Voicebox; the UI switches on the string to drive the
    banner's terminal states. ``progress`` is normalized to 0.0-1.0 on
    the backend side regardless of whether Voicebox emitted 0-100."""
    model_name: str
    status: str
    progress: float
    message: Optional[str] = None


# --- Characters (§9.3) ------------------------------------------------------

EstimatedLineCount = Literal["main", "supporting", "minor", "background"]


class CharacterOut(BaseModel):
    id: str
    project_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    gender: Optional[Gender] = None
    age_estimate: Optional[AgeRange] = None
    description: Optional[str] = None
    speaking_style: Optional[str] = None
    character_archetype: Optional[str] = None
    first_appearance_chapter: Optional[int] = None
    estimated_line_count: Optional[EstimatedLineCount] = None
    line_count: Optional[int] = None
    is_narrator: bool = False
    voice_id: Optional[str] = None
    engine_override: Optional[EnginePreference] = None
    notes: Optional[str] = None


class CharacterUpdate(BaseModel):
    """PATCH /api/characters/{id}. Manual-override surface for the casting gate."""
    voice_id: Optional[str] = None
    engine_override: Optional[EnginePreference] = None
    notes: Optional[str] = None
    # Name-level edits live behind a separate flow; keeping PATCH focused on
    # casting overrides avoids silent breakage of Phase-4 attribution once it
    # wires up.


# --- Jobs (§9.8) ------------------------------------------------------------

JobStatusValue = Literal[
    "queued", "running", "awaiting_response", "complete", "failed"
]


class JobOut(BaseModel):
    id: str
    project_id: Optional[str] = None
    kind: str  # Chorus-internal name; spec §9.8 calls it "type"
    status: JobStatusValue
    progress: float = 0.0
    message: Optional[str] = None
    payload: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    updated_at: str


# --- Extract / Auto-cast trigger responses ---------------------------------


class ExtractCastResponse(BaseModel):
    job_id: str
    request_path: str
    book_text_chars: int
    truncated: bool
    warnings: list[str] = Field(default_factory=list)


class AutoCastResponse(BaseModel):
    job_id: str
    request_path: str
    cast_size: int
    voice_library_size: int


# --- Segments (§9.5) -------------------------------------------------------


class SegmentCharacter(BaseModel):
    """Expanded character info embedded in SegmentOut for the review UI."""
    id: str
    name: str
    character_archetype: Optional[str] = None
    voice_id: Optional[str] = None


class SegmentOut(BaseModel):
    id: str
    chapter_id: str
    order_index: int
    text: str
    render_mode: RenderMode
    emotion_tags: list[str] = Field(default_factory=list)
    confidence: Optional[int] = None
    notes: Optional[str] = None
    character: Optional[SegmentCharacter] = None
    voice_override_id: Optional[str] = None
    audio_path: Optional[str] = None
    duration_ms: Optional[int] = None
    status: str = "pending"
    text_modified: bool = False
    approved_at: Optional[str] = None
    # Phase 5 remediation — read-only; set by the generation pipeline when
    # Voicebox returns a generation id. Null on legacy/pre-remediation audio.
    voicebox_generation_id: Optional[str] = None
    created_at: str
    updated_at: str


class SegmentUpdate(BaseModel):
    """PATCH /api/segments/{id}. Manual-override surface for review."""
    character_id: Optional[str] = None
    render_mode: Optional[RenderMode] = None
    emotion_tags: Optional[list[str]] = None
    text: Optional[str] = None
    notes: Optional[str] = None


class BulkReassignChanges(BaseModel):
    character_id: Optional[str] = None
    render_mode: Optional[RenderMode] = None
    add_emotion_tags: Optional[list[str]] = None
    remove_emotion_tags: Optional[list[str]] = None


class BulkReassignRequest(BaseModel):
    segment_ids: list[str]
    changes: BulkReassignChanges


class BulkReassignResponse(BaseModel):
    updated: int


class AttributeResponse(BaseModel):
    job_id: str
    request_path: str
    chapter_chars: int
    cast_size: int


class AttributeAllResponse(BaseModel):
    chapter_count: int
    job_ids: list[str] = Field(default_factory=list)
    skipped_chapter_ids: list[str] = Field(default_factory=list)  # already had segments


# --- Pronunciations (§9.6) -------------------------------------------------


PronunciationCategory = Literal[
    "character_name", "place", "proper_noun", "phrase", "other"
]


class PronunciationBase(BaseModel):
    term: str
    phonetic: str
    ipa: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[PronunciationCategory] = None
    notes: Optional[str] = None
    source: Optional[str] = None


class PronunciationCreate(PronunciationBase):
    pass


class PronunciationUpdate(BaseModel):
    term: Optional[str] = None
    phonetic: Optional[str] = None
    ipa: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[PronunciationCategory] = None
    notes: Optional[str] = None
    source: Optional[str] = None


class PronunciationOut(PronunciationBase):
    id: str
    project_id: Optional[str] = None   # null for global entries
    created_at: str
    updated_at: str


class MergedPronunciationOut(BaseModel):
    """Phase 5 — what the generation pipeline will actually read.

    Unions project + global entries with project wins. Keyed case-insensitively
    in the helper; this DTO preserves the stored ``term`` casing for display.
    """
    term: str
    phonetic: str
    ipa: Optional[str] = None
    confidence: Optional[float] = None
    source: Literal["global", "project"]
    origin_id: str


class PromoteToGlobalRequest(BaseModel):
    delete_project_entry: bool = True


class PronunciationExtractResponse(BaseModel):
    job_id: str
    request_path: str
    book_text_chars: int
    truncated: bool
    cast_size: int
    warnings: list[str] = Field(default_factory=list)


class ChapterMeta(BaseModel):
    """GET /api/chapters/{id} — metadata shape for the review UI toolbar.

    Mirrors ChapterOut but adds resolved pov_character_name + segment_count so
    the client doesn't need a second round-trip to render the header.
    """
    id: str
    project_id: str
    number: int
    title: Optional[str] = None
    word_count: Optional[int] = None
    pov_character_id: Optional[str] = None
    pov_character_name: Optional[str] = None
    segment_count: int = 0


# --- Generation API (Phase 5, §10.5) ---------------------------------------


class GenerationEstimateOut(BaseModel):
    """Seconds-based TTS time estimate.

    ``segments`` is only meaningful for chapter-level estimates; segment-level
    estimates always return 1. ``human_label`` is preformatted for the UI
    ("~8 min", "32 s", "~1.3 hr").
    """
    seconds: float
    words: int
    segments: int
    wps_factor: float
    human_label: str


class GenerationTriggerOut(BaseModel):
    """Response from segment-level generate/regenerate POSTs."""
    job_id: str
    estimated_seconds: float


class ChapterGenerationTriggerOut(BaseModel):
    """Response from POST /api/chapters/{id}/generate.

    ``job_ids`` is one id per segment that got enqueued; ``segment_count``
    equals ``len(job_ids)``.
    """
    job_ids: list[str]
    segment_count: int
    total_estimated_seconds: float


class ChapterGenerationStatusOut(BaseModel):
    """Aggregated generation-state snapshot for the chapter review UI.

    ``in_progress_job_ids`` lists ``generate_segment`` jobs in
    queued/running state whose payload's ``segment_id`` belongs to this
    chapter — the UI can use them to poll /api/jobs/{id}.
    """
    total: int
    pending: int
    generating: int
    generated: int
    approved: int
    error: int
    in_progress_job_ids: list[str]


# --- Playback + assembly (Phase 6, §9.7) ------------------------------------


class PlaybackStateOut(BaseModel):
    project_id: str
    chapter_id: Optional[str] = None
    current_segment_id: Optional[str] = None
    position_ms: int = 0
    speed: float = 1.0
    updated_at: str


class PlaybackStateUpsert(BaseModel):
    """PATCH /api/projects/{id}/playback-state. Any subset of fields may be
    provided; unset means leave unchanged."""
    chapter_id: Optional[str] = None
    current_segment_id: Optional[str] = None
    position_ms: Optional[int] = None
    speed: Optional[float] = None


class ChapterAssemblyOut(BaseModel):
    id: str
    chapter_id: str
    audio_path: str
    duration_ms: int
    segment_hash: str
    created_at: str
    updated_at: str


class AssemblyStatusOut(BaseModel):
    """GET /api/chapters/{id}/assembly — used by the player UI to decide
    whether to stream the concatenated chapter file or trigger an assembly
    job first."""
    chapter_id: str
    ready: bool
    duration_ms: Optional[int] = None
    assembling: bool = False
    progress: int = 0        # 0-100
    from_cache: bool = False
    hash: Optional[str] = None
    missing_segments: list[str] = Field(default_factory=list)


class SegmentTimingOut(BaseModel):
    """Per-segment timing row in the assembly timeline.

    ``text`` is the full segment body — the player's synced-transcript view
    renders the whole thing so users can read along.

    ``text_preview`` stays truncated to ~80 chars for UIs that want a scrub
    tooltip or a compact review-table column without pulling full bodies."""
    segment_id: str
    order_index: int
    start_ms: int
    end_ms: int
    duration_ms: int
    speaker_name: Optional[str] = None
    text: str
    text_preview: str


class AssemblyTriggerOut(BaseModel):
    """Response from POST /api/chapters/{id}/assemble.

    ``job_id`` is null when the cache short-circuits the request
    (``from_cache=True`` + matching hash + file on disk) — the caller can
    immediately fetch ``/audio`` without polling a job.
    """
    chapter_id: str
    job_id: Optional[str] = None
    from_cache: bool
