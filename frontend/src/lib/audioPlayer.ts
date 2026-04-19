/**
 * Singleton PlayerController wrapping a single HTMLAudioElement.
 *
 * Design rationale — the controller owns the audio element and the
 * store-sync side effects. Routes react to store changes; they should
 * NOT new up their own <audio> elements. That keeps cross-route
 * persistence trivial (play the chapter on the full-screen player,
 * navigate away, controls in the mini-player stay live).
 *
 * Why a DOM event for chapter-ended instead of a callback? The
 * controller is project/chapter-list agnostic — it doesn't know how to
 * fetch the next chapter. When a chapter ends with auto-advance on, we
 * dispatch `chorus:chapter-ended` on `window`; the Player route (which
 * already has the chapter list in scope) listens and calls `next()`.
 * Not elegant but keeps the controller singleton-simple.
 */

import { api, type Chapter, type SegmentTiming } from "./api";
import { usePlayerStore } from "../stores/playerStore";

class PlayerController {
  private audio: HTMLAudioElement | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;

  private ensureAudio(): HTMLAudioElement {
    if (this.audio) return this.audio;
    const a = new Audio();
    a.preload = "auto";
    // Native pitch preservation is the primary strategy. Flagged on all
    // three vendor names because Safari still ships the webkit prefix,
    // and older Firefox used moz. Unknown prefixes are ignored silently.
    (a as unknown as { preservesPitch?: boolean }).preservesPitch = true;
    (a as unknown as { mozPreservesPitch?: boolean }).mozPreservesPitch = true;
    (a as unknown as { webkitPreservesPitch?: boolean }).webkitPreservesPitch =
      true;
    this.audio = a;

    const set = usePlayerStore.setState;
    a.addEventListener("timeupdate", () => {
      const posMs = Math.floor(a.currentTime * 1000);
      set({ positionMs: posMs });
      this.syncSegment(posMs);
      this.scheduleSave();
    });
    a.addEventListener("loadedmetadata", () => {
      const dur = Number.isFinite(a.duration)
        ? Math.floor(a.duration * 1000)
        : 0;
      set({ durationMs: dur, status: "ready" });
    });
    a.addEventListener("ended", () => {
      void this.handleEnded();
    });
    a.addEventListener("error", () =>
      set({ status: "error", assemblyError: "Audio element error" }),
    );
    a.addEventListener("playing", () => set({ status: "playing" }));
    a.addEventListener("pause", () => {
      if (usePlayerStore.getState().status !== "error") set({ status: "paused" });
    });
    a.addEventListener("waiting", () => set({ status: "buffering" }));

    return a;
  }

  async loadChapter(projectIdOrSlug: string, chapterId: string): Promise<void> {
    const set = usePlayerStore.setState;
    // 1. Store project + clear per-load state.
    set({
      projectIdOrSlug,
      chapterId,
      status: "loading",
      positionMs: 0,
      durationMs: 0,
      currentSegmentId: null,
      currentSegmentIndex: -1,
      assemblyProgress: 0,
      assemblyError: null,
      missingSegments: [],
    });

    // 2. Try to restore the user's last position — but only if the saved
    //    row points at THIS chapter. Users switching chapters should not
    //    inherit a position from some other chapter.
    let restorePositionMs = 0;
    try {
      const playback = await api.getPlaybackState(projectIdOrSlug);
      if (playback?.chapter_id === chapterId) {
        restorePositionMs = playback.position_ms ?? 0;
      }
    } catch {
      /* non-fatal — just start from zero */
    }

    // 3. Trigger assembly. from_cache short-circuits the poll.
    let trigger;
    try {
      trigger = await api.triggerAssembly(chapterId);
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Assembly failed";
      set({ status: "error", assemblyError: message });
      return;
    }

    // 4. Poll until ready (skipped if cache hit returned the file).
    if (!trigger.from_cache) {
      const ok = await this.pollAssembly(chapterId);
      if (!ok) return;
    }

    // 5. Fetch timings. Missing timings aren't fatal — UI just loses
    //    segment highlighting, playback continues.
    let timings: SegmentTiming[] = [];
    try {
      timings = await api.chapterSegmentTimings(chapterId);
    } catch {
      /* ignore — no highlights */
    }
    set({ segmentTimings: timings });

    // 6. Wire audio src.
    const audio = this.ensureAudio();
    audio.src = api.chapterAudioUrl(chapterId);
    audio.load();

    // 7. On metadata, restore position (one-shot listener).
    if (restorePositionMs > 0) {
      const onReady = () => {
        try {
          audio.currentTime = restorePositionMs / 1000;
        } catch {
          /* ignore — browser may refuse out-of-range seeks */
        }
        audio.removeEventListener("loadedmetadata", onReady);
      };
      audio.addEventListener("loadedmetadata", onReady);
    }
  }

  private async pollAssembly(chapterId: string): Promise<boolean> {
    const set = usePlayerStore.setState;
    const deadline = Date.now() + 120_000; // 2 min max wait
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const st = await api.chapterAssemblyStatus(chapterId);
        set({
          assemblyProgress: st.progress,
          missingSegments: st.missing_segments,
        });
        if (st.missing_segments.length > 0) {
          set({
            status: "error",
            assemblyError: `${st.missing_segments.length} segments missing audio`,
          });
          return false;
        }
        if (st.ready) return true;
      } catch (e) {
        const message =
          e instanceof Error ? e.message : "Assembly polling failed";
        set({ status: "error", assemblyError: message });
        return false;
      }
    }
    set({ status: "error", assemblyError: "Assembly timed out after 2 minutes" });
    return false;
  }

  play(): void {
    this.ensureAudio()
      .play()
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        usePlayerStore.setState({ status: "error", assemblyError: message });
      });
  }

  pause(): void {
    this.audio?.pause();
  }

  seek(ms: number): void {
    const a = this.ensureAudio();
    if (a.readyState >= 1) a.currentTime = ms / 1000;
    usePlayerStore.setState({ positionMs: ms });
    this.scheduleSave();
  }

  setSpeed(speed: number): void {
    const a = this.ensureAudio();
    a.playbackRate = speed;
    usePlayerStore.setState({ speed });
    this.scheduleSave();
  }

  /** Advance to the next chapter in order. Returns false when already at end. */
  async next(chaptersInOrder: Chapter[]): Promise<boolean> {
    const s = usePlayerStore.getState();
    if (!s.projectIdOrSlug || !s.chapterId) return false;
    const idx = chaptersInOrder.findIndex((c) => c.id === s.chapterId);
    if (idx < 0 || idx >= chaptersInOrder.length - 1) return false;
    const nextCh = chaptersInOrder[idx + 1];
    await this.loadChapter(s.projectIdOrSlug, nextCh.id);
    this.play();
    return true;
  }

  async previous(chaptersInOrder: Chapter[]): Promise<boolean> {
    const s = usePlayerStore.getState();
    if (!s.projectIdOrSlug || !s.chapterId) return false;
    const idx = chaptersInOrder.findIndex((c) => c.id === s.chapterId);
    if (idx <= 0) return false;
    const prevCh = chaptersInOrder[idx - 1];
    await this.loadChapter(s.projectIdOrSlug, prevCh.id);
    this.play();
    return true;
  }

  skip(seconds: number): void {
    const a = this.ensureAudio();
    if (a.readyState >= 1) {
      a.currentTime = Math.max(
        0,
        Math.min(a.duration || 0, a.currentTime + seconds),
      );
    }
  }

  close(): void {
    if (this.audio) {
      try {
        this.audio.pause();
      } catch {
        /* ignore */
      }
      this.audio.src = "";
      this.audio = null;
    }
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = null;
    }
    usePlayerStore.getState().reset();
  }

  private syncSegment(positionMs: number): void {
    const { segmentTimings, currentSegmentId, setCurrentSegment } =
      usePlayerStore.getState();
    if (!segmentTimings.length) return;
    // Binary search: first timing where start_ms <= pos < end_ms.
    let lo = 0;
    let hi = segmentTimings.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const t = segmentTimings[mid];
      if (positionMs < t.start_ms) hi = mid - 1;
      else if (positionMs >= t.end_ms) lo = mid + 1;
      else {
        found = mid;
        break;
      }
    }
    if (found < 0) {
      if (currentSegmentId !== null) setCurrentSegment(null, -1);
      return;
    }
    const t = segmentTimings[found];
    if (t.segment_id !== currentSegmentId) setCurrentSegment(t.segment_id, found);
  }

  private scheduleSave(): void {
    // Debounce — one PATCH per 5s window is plenty for a 30-min chapter.
    if (this.saveTimer) return;
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      this.savePlaybackState().catch(() => {
        /* swallow — retry happens on the next save */
      });
    }, 5000);
  }

  private async savePlaybackState(): Promise<void> {
    const s = usePlayerStore.getState();
    if (!s.projectIdOrSlug || !s.chapterId) return;
    await api.upsertPlaybackState(s.projectIdOrSlug, {
      chapter_id: s.chapterId,
      current_segment_id: s.currentSegmentId,
      position_ms: s.positionMs,
      speed: s.speed,
    });
  }

  private async handleEnded(): Promise<void> {
    const s = usePlayerStore.getState();
    if (!s.autoAdvance) {
      usePlayerStore.setState({ status: "paused" });
      return;
    }
    // The Player route owns the chapter list; dispatch an event for it
    // to pick up. Keeping the controller project-list-agnostic means the
    // mini-player can live anywhere and still get auto-advance for free.
    window.dispatchEvent(
      new CustomEvent("chorus:chapter-ended", {
        detail: {
          projectIdOrSlug: s.projectIdOrSlug,
          endedChapterId: s.chapterId,
        },
      }),
    );
  }
}

export const playerController = new PlayerController();
