import type {
  AgeRange,
  EnginePreference,
  Gender,
  Pace,
  Pool,
  Register,
  Timbre,
} from "./constants";

export type ProjectStatus =
  | "ingesting"
  | "casting"
  | "attributing"
  | "generating"
  | "assembling"
  | "complete"
  | "error";

export interface Project {
  id: string;
  slug: string;
  title: string;
  author: string | null;
  language: string;
  status: ProjectStatus;
  mode: "automated" | "director";
  pov_narrator_enabled: boolean;
  ambient_enabled: boolean;
  cover_art_path: string | null;
  source_path: string | null;
  total_duration_ms: number | null;
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  chapter_count: number;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: string;
  project_id: string;
  number: number;
  title: string | null;
  word_count: number | null;
  estimated_duration_ms: number | null;
  status: string;
  pov_character_id: string | null;
  ambient_scene_tag: string | null;
  // Added in phase4-complete: list_chapters now LEFT JOINs a COUNT on
  // segments. Optional for backwards compat with stale backends.
  segment_count?: number;
}

export interface IngestResult {
  project_id: string;
  source_kind: "txt" | "epub";
  title: string | null;
  author: string | null;
  chapters_detected: number;
  chapters: Chapter[];
  warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let body = "";
    try {
      body = await res.text();
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// --- Characters + Jobs (§9.3, §9.8) -----------------------------------------

export type EstimatedLineCount = "main" | "supporting" | "minor" | "background";

export interface Character {
  id: string;
  project_id: string;
  name: string;
  aliases: string[];
  gender: Gender | null;
  age_estimate: AgeRange | null;
  description: string | null;
  speaking_style: string | null;
  character_archetype: string | null;
  first_appearance_chapter: number | null;
  estimated_line_count: EstimatedLineCount | null;
  line_count: number | null;
  is_narrator: boolean;
  voice_id: string | null;
  engine_override: EnginePreference | null;
  notes: string | null;
}

export interface CharacterUpdate {
  voice_id?: string | null;
  engine_override?: EnginePreference | null;
  notes?: string | null;
}

export type JobStatus =
  | "queued"
  | "running"
  | "awaiting_response"
  | "complete"
  | "failed";

export interface Job {
  id: string;
  project_id: string | null;
  kind: string;
  status: JobStatus;
  progress: number;
  message: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExtractCastResult {
  job_id: string;
  request_path: string;
  book_text_chars: number;
  truncated: boolean;
  warnings: string[];
}

export interface AutoCastResult {
  job_id: string;
  request_path: string;
  cast_size: number;
  voice_library_size: number;
}

// --- Attribution + segments (§9.5, Phase 4) --------------------------------

export type RenderMode =
  | "prose"
  | "dialogue"
  | "epigraph"
  | "letter"
  | "poetry"
  | "song_lyrics"
  | "emphasis"
  | "thought"
  | "chapter_heading";

export interface SegmentCharacter {
  id: string;
  name: string;
  character_archetype: string | null;
  voice_id: string | null;
}

export interface Segment {
  id: string;
  chapter_id: string;
  order_index: number;
  text: string;
  render_mode: RenderMode;
  emotion_tags: string[];
  confidence: number | null;
  notes: string | null;
  character: SegmentCharacter | null;
  voice_override_id: string | null;
  audio_path: string | null;
  duration_ms: number | null;
  status: string;
  text_modified: boolean;
  /** Phase-5: ISO-8601 UTC timestamp set when the segment is approved;
   * null once rejected or while still in pending/generating/generated/error. */
  approved_at?: string | null;
  created_at: string;
  updated_at: string;
}

// --- Generation (Phase 5, §10.5) ------------------------------------------

export interface GenerationEstimate {
  seconds: number;
  words: number;
  segments: number;
  wps_factor: number;
  human_label: string;
}

export interface GenerationTriggerResult {
  job_id: string;
  estimated_seconds: number;
}

export interface ChapterGenerationTriggerResult {
  job_ids: string[];
  segment_count: number;
  total_estimated_seconds: number;
}

export interface ChapterGenerationStatus {
  total: number;
  pending: number;
  generating: number;
  generated: number;
  approved: number;
  error: number;
  in_progress_job_ids: string[];
}

// --- Playback + assembly (Phase 6, §9.7) -----------------------------------

export interface PlaybackState {
  project_id: string;
  chapter_id: string | null;
  current_segment_id: string | null;
  position_ms: number;
  speed: number;
  updated_at: string;
}

export interface PlaybackStateUpsert {
  chapter_id?: string | null;
  current_segment_id?: string | null;
  position_ms?: number;
  speed?: number;
}

export interface AssemblyTrigger {
  chapter_id: string;
  job_id: string | null;
  from_cache: boolean;
}

export interface AssemblyStatus {
  chapter_id: string;
  ready: boolean;
  duration_ms: number | null;
  assembling: boolean;
  progress: number;
  from_cache: boolean;
  hash: string | null;
  missing_segments: string[];
}

export interface SegmentTiming {
  segment_id: string;
  order_index: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  speaker_name: string | null;
  text_preview: string;
}

export interface SegmentUpdate {
  character_id?: string | null;
  render_mode?: RenderMode;
  emotion_tags?: string[];
  text?: string;
  notes?: string | null;
}

export interface BulkReassignChanges {
  character_id?: string | null;
  render_mode?: RenderMode;
  emotion_tags?: string[];
}

export interface BulkReassignRequest {
  segment_ids: string[];
  changes: BulkReassignChanges;
}

export interface BulkReassignResponse {
  updated: number;
}

export interface ChapterMeta {
  id: string;
  project_id: string;
  number: number;
  title: string;
  word_count: number;
  pov_character_id: string | null;
  pov_character_name: string | null;
  segment_count: number;
}

export interface AttributeResponse {
  job_id: string;
  request_path: string;
  chapter_chars: number;
  cast_size: number;
}

export interface AttributeAllResponse {
  chapter_count: number;
  job_ids: string[];
  skipped_chapter_ids: string[];
}

// --- Pronunciations (§9.6, Phase 5) ----------------------------------------

export type PronunciationCategory =
  | "character_name"
  | "place"
  | "proper_noun"
  | "phrase"
  | "other";

export interface Pronunciation {
  id: string;
  project_id: string | null; // null for global
  term: string;
  phonetic: string;
  ipa: string | null;
  confidence: number | null;
  category: PronunciationCategory | null;
  notes: string | null;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface PronunciationCreate {
  term: string;
  phonetic: string;
  ipa?: string | null;
  confidence?: number | null;
  category?: PronunciationCategory | null;
  notes?: string | null;
  source?: string | null;
}

export type PronunciationUpdate = Partial<PronunciationCreate>;

export interface MergedPronunciationEntry {
  term: string;
  phonetic: string;
  ipa: string | null;
  confidence: number | null;
  source: "global" | "project";
  origin_id: string;
}

export interface PronunciationExtractResult {
  job_id: string;
  request_path: string;
  book_text_chars: number;
  truncated: boolean;
  cast_size: number;
  warnings: string[];
}

// --- Voice library (§7.2) ---------------------------------------------------

export interface Voice {
  id: string;
  voicebox_profile_id: string | null;
  display_name: string;
  gender: Gender | null;
  age_range: AgeRange | null;
  accent: string | null;
  tone: string[];
  timbre: Timbre | null;
  pace: Pace | null;
  register: Register | null;
  character_archetypes: string[];
  pool: Pool;
  engine_preference: EnginePreference | null;
  sample_text: string | null;
  source_notes: string | null;
  tags: string[];
  sample_audio_path: string | null;
  has_sample_audio: boolean;
  times_used: number;
  added_at: string;
  updated_at: string;
}

export interface VoiceCreate {
  display_name: string;
  gender?: Gender | null;
  age_range?: AgeRange | null;
  accent?: string | null;
  tone?: string[];
  timbre?: Timbre | null;
  pace?: Pace | null;
  register?: Register | null;
  character_archetypes?: string[];
  pool: Pool;
  engine_preference?: EnginePreference | null;
  sample_text?: string | null;
  source_notes?: string | null;
  tags?: string[];
}

export type VoiceUpdate = Partial<VoiceCreate>;

export interface VoicePoolCounts {
  narrator: number;
  main: number;
  background: number;
}

export interface VoiceboxStatus {
  enabled: boolean;
  reachable: boolean | null;
  base_url: string;
  note: string;
}

/** Phase-5 richer health shape returned by GET /api/voicebox/status. */
export interface VoiceboxHealth {
  enabled: boolean;
  reachable: boolean;
  base_url: string;
  version: string | null;
  profile_count: number | null;
  available_engines: string[];
  error: string | null;
}

export interface VoiceFilter {
  pool?: Pool;
  gender?: Gender;
  q?: string;
}

function buildVoicesQuery(filter: VoiceFilter): string {
  const params = new URLSearchParams();
  if (filter.pool) params.set("pool", filter.pool);
  if (filter.gender) params.set("gender", filter.gender);
  if (filter.q && filter.q.trim()) params.set("q", filter.q.trim());
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function sampleAudioUrl(voiceId: string): string {
  // Cache-bust with the voice's updated_at isn't reliable (we don't have it
  // here); caller can append ?t=<ts> if needed.
  return `/api/voices/${voiceId}/sample`;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),

  createProject: (body: {
    title: string;
    author?: string | null;
    language?: string;
    mode?: "automated" | "director";
  }) =>
    request<Project>("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  getProject: (id: string) => request<Project>(`/api/projects/${id}`),

  deleteProject: (id: string) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  listChapters: (id: string) =>
    request<Chapter[]>(`/api/projects/${id}/chapters`),

  ingest: async (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<IngestResult>(`/api/projects/${id}/ingest`, {
      method: "POST",
      body: fd,
    });
  },

  // ---- Voices ----

  listVoices: (filter: VoiceFilter = {}) =>
    request<Voice[]>(`/api/voices${buildVoicesQuery(filter)}`),

  getVoice: (id: string) => request<Voice>(`/api/voices/${id}`),

  voicePoolCounts: () => request<VoicePoolCounts>("/api/voices/pools/summary"),

  /**
   * @deprecated Use `voiceboxHealth()` instead (Phase 5). The old endpoint
   * 308-redirects to `/api/voicebox/status`, so fetch follows it transparently
   * and the legacy shape is still returned only because the backend no longer
   * serves it directly — callers should migrate.
   */
  voiceboxStatus: () => request<VoiceboxStatus>("/api/voices/voicebox/status"),

  voiceboxHealth: () => request<VoiceboxHealth>("/api/voicebox/status"),

  createVoice: async (body: VoiceCreate, audio?: File | null) => {
    const fd = new FormData();
    fd.append("voice_json", JSON.stringify(body));
    if (audio) fd.append("audio", audio);
    return request<Voice>("/api/voices", { method: "POST", body: fd });
  },

  updateVoice: (id: string, body: VoiceUpdate) =>
    request<Voice>(`/api/voices/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  replaceVoiceSample: async (id: string, audio: File) => {
    const fd = new FormData();
    fd.append("audio", audio);
    return request<Voice>(`/api/voices/${id}/sample`, {
      method: "POST",
      body: fd,
    });
  },

  deleteVoiceSample: (id: string) =>
    request<Voice>(`/api/voices/${id}/sample`, { method: "DELETE" }),

  deleteVoice: (id: string) =>
    request<void>(`/api/voices/${id}`, { method: "DELETE" }),

  // ---- Characters + Casting ----

  listCharacters: (projectIdOrSlug: string) =>
    request<Character[]>(`/api/projects/${projectIdOrSlug}/characters`),

  updateCharacter: (id: string, body: CharacterUpdate) =>
    request<Character>(`/api/characters/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  extractCast: (projectIdOrSlug: string) =>
    request<ExtractCastResult>(`/api/projects/${projectIdOrSlug}/extract-cast`, {
      method: "POST",
    }),

  autoCast: (projectIdOrSlug: string) =>
    request<AutoCastResult>(`/api/projects/${projectIdOrSlug}/auto-cast`, {
      method: "POST",
    }),

  // ---- Jobs ----

  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  listProjectJobs: (
    projectIdOrSlug: string,
    filter: { status?: JobStatus; kind?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (filter.status) params.set("status", filter.status);
    if (filter.kind) params.set("kind", filter.kind);
    const qs = params.toString();
    return request<Job[]>(
      `/api/projects/${projectIdOrSlug}/jobs${qs ? "?" + qs : ""}`,
    );
  },

  // ---- Attribution + segments (Phase 4) ----

  getChapter: (chapterId: string) =>
    request<ChapterMeta>(`/api/chapters/${chapterId}`),

  listSegments: (chapterId: string) =>
    request<Segment[]>(`/api/chapters/${chapterId}/segments`),

  updateSegment: (segmentId: string, body: SegmentUpdate) =>
    request<Segment>(`/api/segments/${segmentId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  bulkReassignSegments: (body: BulkReassignRequest) =>
    request<BulkReassignResponse>("/api/segments/bulk-reassign", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  attributeChapter: (chapterId: string) =>
    request<AttributeResponse>(`/api/chapters/${chapterId}/attribute`, {
      method: "POST",
    }),

  attributeAllChapters: (projectIdOrSlug: string) =>
    request<AttributeAllResponse>(
      `/api/projects/${projectIdOrSlug}/attribute-all`,
      { method: "POST" },
    ),

  // ---- Pronunciations (Phase 5) ----

  listGlobalPronunciations: () =>
    request<Pronunciation[]>("/api/pronunciations/global"),

  createGlobalPronunciation: (body: PronunciationCreate) =>
    request<Pronunciation>("/api/pronunciations/global", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  updateGlobalPronunciation: (id: string, body: PronunciationUpdate) =>
    request<Pronunciation>(`/api/pronunciations/global/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteGlobalPronunciation: (id: string) =>
    request<void>(`/api/pronunciations/global/${id}`, { method: "DELETE" }),

  listProjectPronunciations: (projectIdOrSlug: string) =>
    request<Pronunciation[]>(
      `/api/projects/${projectIdOrSlug}/pronunciations`,
    ),

  createProjectPronunciation: (
    projectIdOrSlug: string,
    body: PronunciationCreate,
  ) =>
    request<Pronunciation>(
      `/api/projects/${projectIdOrSlug}/pronunciations`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  updatePronunciation: (id: string, body: PronunciationUpdate) =>
    request<Pronunciation>(`/api/pronunciations/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  deletePronunciation: (id: string) =>
    request<void>(`/api/pronunciations/${id}`, { method: "DELETE" }),

  promotePronunciationToGlobal: (
    id: string,
    opts: { deleteProjectEntry?: boolean } = {},
  ) =>
    request<Pronunciation>(`/api/pronunciations/${id}/promote-to-global`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        delete_project_entry: opts.deleteProjectEntry ?? true,
      }),
    }),

  extractPronunciations: (projectIdOrSlug: string) =>
    request<PronunciationExtractResult>(
      `/api/projects/${projectIdOrSlug}/pronunciations/extract`,
      { method: "POST" },
    ),

  listMergedPronunciations: (projectIdOrSlug: string) =>
    request<MergedPronunciationEntry[]>(
      `/api/projects/${projectIdOrSlug}/pronunciations/merged`,
    ),

  // ---- Generation (Phase 5, §10.5) ----

  generateSegment: (segmentId: string) =>
    request<GenerationTriggerResult>(
      `/api/segments/${segmentId}/generate`,
      { method: "POST" },
    ),

  regenerateSegment: (segmentId: string) =>
    request<GenerationTriggerResult>(
      `/api/segments/${segmentId}/regenerate`,
      { method: "POST" },
    ),

  approveSegment: (segmentId: string) =>
    request<Segment>(`/api/segments/${segmentId}/approve`, {
      method: "POST",
    }),

  rejectSegment: (segmentId: string) =>
    request<Segment>(`/api/segments/${segmentId}/reject`, {
      method: "POST",
    }),

  /** Returns a URL string for use in an <audio src>. Does NOT fetch.
   * Pass `approved=true` to get the approved track. Callers can append
   * `?t=<timestamp>` to bust the browser cache after regeneration. */
  segmentAudioUrl: (segmentId: string, approved = false): string =>
    approved
      ? `/api/segments/${segmentId}/audio/approved`
      : `/api/segments/${segmentId}/audio`,

  generateChapter: (chapterId: string) =>
    request<ChapterGenerationTriggerResult>(
      `/api/chapters/${chapterId}/generate`,
      { method: "POST" },
    ),

  chapterGenerationEstimate: (chapterId: string) =>
    request<GenerationEstimate>(
      `/api/chapters/${chapterId}/generation-estimate`,
    ),

  chapterGenerationStatus: (chapterId: string) =>
    request<ChapterGenerationStatus>(
      `/api/chapters/${chapterId}/generation-status`,
    ),

  // ---- Playback + assembly (Phase 6, §9.7) ----

  /** Returns null on 404 (no saved state yet or project missing). All other
   * errors (network, 5xx) still throw. The player's "resume where I left off"
   * flow treats null the same as "start from zero". */
  getPlaybackState: async (
    projectIdOrSlug: string,
  ): Promise<PlaybackState | null> => {
    const res = await fetch(
      `/api/projects/${projectIdOrSlug}/playback`,
    );
    if (res.status === 404) return null;
    if (!res.ok) {
      let body = "";
      try {
        body = await res.text();
      } catch {
        /* ignore */
      }
      throw new Error(`${res.status} ${res.statusText}: ${body}`);
    }
    return (await res.json()) as PlaybackState;
  },

  upsertPlaybackState: (
    projectIdOrSlug: string,
    body: PlaybackStateUpsert,
  ) =>
    request<PlaybackState>(`/api/projects/${projectIdOrSlug}/playback`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  triggerAssembly: (chapterId: string, force = false) => {
    const qs = force ? "?force=true" : "";
    return request<AssemblyTrigger>(
      `/api/chapters/${chapterId}/assemble${qs}`,
      { method: "POST" },
    );
  },

  chapterAssemblyStatus: (chapterId: string) =>
    request<AssemblyStatus>(`/api/chapters/${chapterId}/assembly-status`),

  /** Returns a URL string for use in `<audio src>`. Does NOT fetch. Cache-bust
   * with `?t=<timestamp>` if a reassembly must invalidate browser cache. */
  chapterAudioUrl: (chapterId: string): string =>
    `/api/chapters/${chapterId}/audio`,

  chapterSegmentTimings: (chapterId: string) =>
    request<SegmentTiming[]>(
      `/api/chapters/${chapterId}/segment-timings`,
    ),
};
