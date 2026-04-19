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


class VoiceOut(VoiceBase):
    id: str
    voicebox_profile_id: Optional[str] = None  # Adjustment A — always null in Phase 2
    sample_audio_path: Optional[str] = None
    has_sample_audio: bool = False
    times_used: int = 0
    added_at: str
    updated_at: str


class VoicePoolCounts(BaseModel):
    narrator: int = 0
    main: int = 0
    background: int = 0


class VoiceboxStatusOut(BaseModel):
    """GET /api/voices/voicebox/status — surfaced to the UI so it can hide or
    disable generation-dependent controls without making the user guess."""
    enabled: bool
    reachable: Optional[bool] = None  # null when disabled
    base_url: str
    note: str


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
