// Review-screen filter state + helpers. Lives here (not in the route) so the
// TableView, ProseView, and (later) BulkActionsMenu can share the same logic
// without dragging the whole route into tests.

import type { RenderMode, Segment } from "./api";

// Sentinel for "segments without a character assignment" so we can treat
// unattributed lines as a first-class speaker filter. Real character IDs are
// UUIDs so this string can't collide.
export const UNATTRIBUTED_ID = "__unattributed__";

export interface ReviewFiltersState {
  speakers: Set<string>; // character IDs; UNATTRIBUTED_ID for null character
  confidenceMin: number; // 0-100
  confidenceMax: number; // 0-100
  renderModes: Set<RenderMode>; // empty = all modes pass
  onlyWithEmotionTags: boolean;
  onlyWithNotes: boolean;
}

export const EMPTY_FILTERS: ReviewFiltersState = {
  speakers: new Set(),
  confidenceMin: 0,
  confidenceMax: 100,
  renderModes: new Set(),
  onlyWithEmotionTags: false,
  onlyWithNotes: false,
};

export function isFilterActive(f: ReviewFiltersState): boolean {
  return (
    f.speakers.size > 0 ||
    f.confidenceMin > 0 ||
    f.confidenceMax < 100 ||
    f.renderModes.size > 0 ||
    f.onlyWithEmotionTags ||
    f.onlyWithNotes
  );
}

export function countActiveFilters(f: ReviewFiltersState): number {
  let n = 0;
  if (f.speakers.size > 0) n += 1;
  if (f.confidenceMin > 0 || f.confidenceMax < 100) n += 1;
  if (f.renderModes.size > 0) n += 1;
  if (f.onlyWithEmotionTags) n += 1;
  if (f.onlyWithNotes) n += 1;
  return n;
}

export function applyFilters(
  segments: Segment[],
  f: ReviewFiltersState,
): Segment[] {
  if (!isFilterActive(f)) return segments;
  return segments.filter((seg) => {
    // Speaker: if the filter is set, the segment must be in the chosen set.
    if (f.speakers.size > 0) {
      const key = seg.character?.id ?? UNATTRIBUTED_ID;
      if (!f.speakers.has(key)) return false;
    }

    // Confidence: null confidence is treated as 0 so low-coverage rows show up
    // when the user is hunting bad attribution.
    const conf = seg.confidence ?? 0;
    if (conf < f.confidenceMin) return false;
    if (conf > f.confidenceMax) return false;

    // Render mode: empty set means "any mode passes".
    if (f.renderModes.size > 0 && !f.renderModes.has(seg.render_mode)) {
      return false;
    }

    if (f.onlyWithEmotionTags && (seg.emotion_tags?.length ?? 0) === 0) {
      return false;
    }

    if (f.onlyWithNotes && !(seg.notes && seg.notes.trim().length > 0)) {
      return false;
    }

    return true;
  });
}

// --- localStorage persistence -----------------------------------------------

const VIEW_MODE_KEY = "review:view-mode";
export type ViewMode = "prose" | "table";

export function loadViewMode(): ViewMode {
  try {
    const raw = localStorage.getItem(VIEW_MODE_KEY);
    if (raw === "table" || raw === "prose") return raw;
  } catch {
    /* SSR / storage blocked */
  }
  return "prose";
}

export function saveViewMode(mode: ViewMode): void {
  try {
    localStorage.setItem(VIEW_MODE_KEY, mode);
  } catch {
    /* ignore */
  }
}

function filtersKey(chapterId: string): string {
  return `review:filters:${chapterId}`;
}

interface SerializedFilters {
  speakers: string[];
  confidenceMin: number;
  confidenceMax: number;
  renderModes: string[];
  onlyWithEmotionTags: boolean;
  onlyWithNotes: boolean;
}

function serialize(f: ReviewFiltersState): SerializedFilters {
  return {
    speakers: [...f.speakers],
    confidenceMin: f.confidenceMin,
    confidenceMax: f.confidenceMax,
    renderModes: [...f.renderModes],
    onlyWithEmotionTags: f.onlyWithEmotionTags,
    onlyWithNotes: f.onlyWithNotes,
  };
}

function deserialize(raw: unknown): ReviewFiltersState {
  if (!raw || typeof raw !== "object") return EMPTY_FILTERS;
  const r = raw as Partial<SerializedFilters>;
  const speakers = Array.isArray(r.speakers) ? r.speakers : [];
  const renderModes = Array.isArray(r.renderModes) ? r.renderModes : [];
  const confMin =
    typeof r.confidenceMin === "number" ? clamp(r.confidenceMin, 0, 100) : 0;
  const confMax =
    typeof r.confidenceMax === "number" ? clamp(r.confidenceMax, 0, 100) : 100;
  return {
    speakers: new Set(speakers.filter((s): s is string => typeof s === "string")),
    confidenceMin: Math.min(confMin, confMax),
    confidenceMax: Math.max(confMin, confMax),
    renderModes: new Set(
      renderModes.filter(
        (m): m is RenderMode =>
          typeof m === "string" &&
          [
            "prose",
            "dialogue",
            "epigraph",
            "letter",
            "poetry",
            "song_lyrics",
            "emphasis",
            "thought",
            "chapter_heading",
          ].includes(m),
      ),
    ),
    onlyWithEmotionTags: Boolean(r.onlyWithEmotionTags),
    onlyWithNotes: Boolean(r.onlyWithNotes),
  };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

export function loadFilters(chapterId: string): ReviewFiltersState {
  if (!chapterId) return EMPTY_FILTERS;
  try {
    const raw = localStorage.getItem(filtersKey(chapterId));
    if (!raw) return EMPTY_FILTERS;
    return deserialize(JSON.parse(raw));
  } catch {
    return EMPTY_FILTERS;
  }
}

export function saveFilters(chapterId: string, f: ReviewFiltersState): void {
  if (!chapterId) return;
  try {
    localStorage.setItem(filtersKey(chapterId), JSON.stringify(serialize(f)));
  } catch {
    /* ignore */
  }
}
