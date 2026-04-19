/**
 * Cross-route model-loading banner state (Phase 5R, Commit 6).
 *
 * The Voicebox TTS model takes 2-4 minutes to load the first time. When a
 * user kicks generation from Chapter Review, we set `modelName` here so
 * the global `<ModelLoadingBanner>` mounted in `<Layout>` becomes visible.
 * The banner polls `/api/voicebox/models/{name}/progress` every second
 * and clears its own state once Voicebox reports `loaded`/`complete`.
 *
 * Why a Zustand store (vs React context)?
 *   * The producer (GenerateModal) and the consumer (Layout > banner)
 *     live in different subtrees and have no common ancestor below
 *     `<App />` — context would need to wrap the whole app.
 *   * Matches the "cross-route client state goes in Zustand" rule
 *     codified in CLAUDE.md alongside `playerStore`.
 *
 * The store is intentionally minimal: a single string slot. The banner
 * derives its progress, label, and dismiss timing from the polled
 * progress endpoint, not from this store.
 */

import { create } from "zustand";

export interface ModelLoadingState {
  /** Voicebox model name currently loading. `null` hides the global
   * banner. Set this when generation triggers a model load; clear it
   * (or let the banner clear it via `onComplete`) once the load
   * finishes — banner-side dismissal also calls `setModelName(null)`
   * after a brief success display. */
  modelName: string | null;
  setModelName: (name: string | null) => void;
}

export const useModelLoadingStore = create<ModelLoadingState>((set) => ({
  modelName: null,
  setModelName: (name) => set({ modelName: name }),
}));
