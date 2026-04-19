// Shared enum choices. Mirror of backend/schemas.py Literals so the UI
// never drifts from server validation.

export const GENDERS = ["male", "female", "nonbinary", "unknown"] as const;
export type Gender = (typeof GENDERS)[number];

export const AGE_RANGES = [
  "child",
  "teen",
  "young_adult",
  "middle_aged",
  "elder",
  "unknown",
] as const;
export type AgeRange = (typeof AGE_RANGES)[number];

export const POOLS = ["narrator", "main", "background"] as const;
export type Pool = (typeof POOLS)[number];

export const TIMBRES = ["light", "medium", "deep", "unknown"] as const;
export type Timbre = (typeof TIMBRES)[number];

export const PACES = ["slow", "measured", "quick", "unknown"] as const;
export type Pace = (typeof PACES)[number];

export const REGISTERS = ["formal", "casual", "rough", "warm", "unknown"] as const;
export type Register = (typeof REGISTERS)[number];

export const ENGINE_PREFERENCES = [
  "auto",
  "chatterbox_turbo",
  "qwen3_tts",
  "humeai_tada",
  "luxtts",
  "unknown",
] as const;
export type EnginePreference = (typeof ENGINE_PREFERENCES)[number];

// Pool targets from §7.3 — shown as guidance in the Voice Library header.
// Adjustment C: these are guidance, not hard caps.
export const POOL_TARGETS: Record<Pool, { min: number; max: number; label: string }> = {
  narrator: { min: 3, max: 5, label: "narrator" },
  main: { min: 20, max: 40, label: "main" },
  background: { min: 5, max: 10, label: "background" },
};

export const AUDIO_ACCEPT = ".wav,.mp3,.m4a,.flac,.ogg,audio/*";

// --- Phase 4: per-chapter attribution review -------------------------------

export const RENDER_MODES = [
  "prose",
  "dialogue",
  "epigraph",
  "letter",
  "poetry",
  "song_lyrics",
  "emphasis",
  "thought",
  "chapter_heading",
] as const;

// Confidence bucket thresholds — green >=85, yellow 70-84, red <70.
export const CONFIDENCE = {
  GREEN_MIN: 85,
  YELLOW_MIN: 70,
  colorFor: (c: number | null | undefined): "green" | "yellow" | "red" | "neutral" => {
    if (c == null) return "neutral";
    if (c >= 85) return "green";
    if (c >= 70) return "yellow";
    return "red";
  },
  hexFor: (c: number | null | undefined): string => {
    const band = CONFIDENCE.colorFor(c);
    if (band === "green") return "#10B981";
    if (band === "yellow") return "#F59E0B";
    if (band === "red") return "#EF4444";
    return "#2A2A2E";
  },
} as const;

export const EMOTION_TAG_SUGGESTIONS = [
  "whispered",
  "shouted",
  "muttered",
  "gentle",
  "cold",
  "angry",
  "amused",
  "sad",
  "urgent",
  "calm",
  "hushed",
  "emphatic",
  "trembling",
  "warm",
  "stern",
];
