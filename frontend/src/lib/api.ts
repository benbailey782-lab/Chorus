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

  voiceboxStatus: () => request<VoiceboxStatus>("/api/voices/voicebox/status"),

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
};
