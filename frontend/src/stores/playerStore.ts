/**
 * Cross-route player state (Phase 6, §9.7).
 *
 * Owns the identity (project + chapter), playback cursor, segment-sync
 * bookkeeping, assembly progress, and the `autoAdvance` preference. The
 * audio element + network work live in `audioPlayer.ts`; this module is
 * pure state and is safe to import from any route/component.
 *
 * The `subscribeWithSelector` middleware lets components (or the
 * controller) subscribe to a specific slice of state without re-rendering
 * on unrelated updates — important because the controller pushes a new
 * `positionMs` every ~250ms during playback.
 */

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type { ChapterMeta, SegmentTiming } from "../lib/api";

export type PlayerStatus =
  | "idle"
  | "loading"
  | "ready"
  | "playing"
  | "paused"
  | "buffering"
  | "error"
  | "finished";

export interface PlayerState {
  // Identity
  projectIdOrSlug: string | null;
  chapterId: string | null;
  chapter: ChapterMeta | null;
  segmentTimings: SegmentTiming[];

  // Playback
  status: PlayerStatus;
  positionMs: number;
  durationMs: number;
  speed: number;

  // Segment sync
  currentSegmentId: string | null;
  currentSegmentIndex: number;

  // Assembly
  assemblyProgress: number;
  assemblyError: string | null;
  missingSegments: string[];

  // Preferences (persisted to localStorage)
  autoAdvance: boolean;

  // Soft-restore hint: when loadChapter restores a non-zero position on
  // page load / refresh, we stash it here so the UI can surface a
  // "Resumed at Xm Ys" chip until the user presses play.
  restoredPositionMs: number | null;

  // Actions
  setStatus: (s: PlayerStatus) => void;
  setPosition: (ms: number) => void;
  setDuration: (ms: number) => void;
  setSpeed: (speed: number) => void;
  setCurrentSegment: (segmentId: string | null, index: number) => void;
  setAssemblyProgress: (pct: number) => void;
  setAssemblyError: (err: string | null) => void;
  setMissingSegments: (ids: string[]) => void;
  setAutoAdvance: (on: boolean) => void;
  clearRestoredPosition: () => void;
  loadProject: (idOrSlug: string) => void;
  loadChapter: (
    chapterId: string,
    chapter: ChapterMeta,
    timings: SegmentTiming[],
  ) => void;
  reset: () => void;
}

const AUTO_ADVANCE_KEY = "player:auto-advance";

function readAutoAdvance(): boolean {
  // Defensive against SSR / private-mode quota errors. Default: on.
  try {
    if (typeof localStorage === "undefined") return true;
    const v = localStorage.getItem(AUTO_ADVANCE_KEY);
    return v === null ? true : v === "true";
  } catch {
    return true;
  }
}

export const usePlayerStore = create<PlayerState>()(
  subscribeWithSelector((set) => ({
    projectIdOrSlug: null,
    chapterId: null,
    chapter: null,
    segmentTimings: [],
    status: "idle",
    positionMs: 0,
    durationMs: 0,
    speed: 1.0,
    currentSegmentId: null,
    currentSegmentIndex: -1,
    assemblyProgress: 0,
    assemblyError: null,
    missingSegments: [],
    autoAdvance: readAutoAdvance(),
    restoredPositionMs: null,

    setStatus: (s) => set({ status: s }),
    setPosition: (ms) => set({ positionMs: ms }),
    setDuration: (ms) => set({ durationMs: ms }),
    setSpeed: (speed) => set({ speed }),
    setCurrentSegment: (currentSegmentId, currentSegmentIndex) =>
      set({ currentSegmentId, currentSegmentIndex }),
    setAssemblyProgress: (assemblyProgress) => set({ assemblyProgress }),
    setAssemblyError: (assemblyError) => set({ assemblyError }),
    setMissingSegments: (missingSegments) => set({ missingSegments }),
    setAutoAdvance: (on) => {
      try {
        if (typeof localStorage !== "undefined") {
          localStorage.setItem(AUTO_ADVANCE_KEY, String(on));
        }
      } catch {
        /* localStorage may be unavailable; in-memory state still wins */
      }
      set({ autoAdvance: on });
    },
    clearRestoredPosition: () => set({ restoredPositionMs: null }),
    loadProject: (idOrSlug) =>
      set({
        projectIdOrSlug: idOrSlug,
        chapterId: null,
        chapter: null,
        segmentTimings: [],
        status: "idle",
        positionMs: 0,
        durationMs: 0,
        currentSegmentId: null,
        currentSegmentIndex: -1,
        assemblyProgress: 0,
        assemblyError: null,
        missingSegments: [],
      }),
    loadChapter: (chapterId, chapter, timings) =>
      set({
        chapterId,
        chapter,
        segmentTimings: timings,
        positionMs: 0,
        currentSegmentId: null,
        currentSegmentIndex: -1,
      }),
    reset: () =>
      set({
        projectIdOrSlug: null,
        chapterId: null,
        chapter: null,
        segmentTimings: [],
        status: "idle",
        positionMs: 0,
        durationMs: 0,
        currentSegmentId: null,
        currentSegmentIndex: -1,
        speed: 1.0,
        assemblyProgress: 0,
        assemblyError: null,
        missingSegments: [],
        restoredPositionMs: null,
      }),
  })),
);
