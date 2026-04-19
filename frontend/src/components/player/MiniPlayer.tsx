import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { playerController } from "../../lib/audioPlayer";
import { usePlayerStore } from "../../stores/playerStore";

/**
 * Persistent mini-player — floating draggable card (Phase 6.5, commit 3).
 *
 * Replaces the Phase-6 full-width bottom strip. Apple Music / Spotify pill
 * style: an absolute-positioned, rounded, translucent card that floats above
 * content and can be dragged to any corner of the viewport.
 *
 * Interaction model
 * -----------------
 * The entire card body is a drag handle, but drag only initiates after a
 * sustained 300 ms press. This avoids stealing taps meant for play/pause or
 * close. Flow:
 *   - pointerdown on card → start 300 ms timer + track start point
 *   - pointermove before timer: if moved > 5 px, cancel timer and treat as
 *     scroll (don't drag, don't click)
 *   - timer fires without significant movement → enter drag mode, capture
 *     pointer
 *   - pointerup before timer → treat as click (but card body isn't itself
 *     clickable; the buttons handle their own taps via stopPropagation)
 *
 * Play/pause and close buttons have their own `onPointerDown` that calls
 * `stopPropagation()` so they always respond to taps regardless of the
 * drag-press logic.
 *
 * Positioning
 * -----------
 * Card position is stored in component state as `{x, y}` (top-left pixel
 * coords) and persisted to localStorage under `player:miniplayer-position`.
 * The persisted record includes the breakpoint so desktop/mobile positions
 * don't collide — if the stored breakpoint doesn't match the current
 * viewport, we fall back to the default corner for the current breakpoint.
 *
 * On pointerup, if the card center is within 50 px of a viewport corner, it
 * snaps to that corner with a smooth CSS transition. Otherwise the card
 * stays where it was released. Resize clamps position back into bounds and
 * re-snaps to the nearest valid corner if the previous position is off
 * screen.
 *
 * Visibility
 * ----------
 * Hidden when no chapter is loaded or when on `/play/:id` (the full player
 * route). Layout decides whether to mount this component; we additionally
 * bail when identity keys are missing.
 */

const STORAGE_KEY = "player:miniplayer-position";
const MOBILE_BREAKPOINT = 768;
const DESKTOP_W = 320;
const DESKTOP_H = 80;
const MOBILE_W = 280;
const MOBILE_H = 72;
const EDGE_MARGIN = 16;
const BOTTOM_NAV_HEIGHT = 64; // 4rem — see Layout.tsx
const DRAG_HOLD_MS = 300;
const DRAG_MOVE_THRESHOLD_PX = 5;
const SNAP_DISTANCE_PX = 50;

type Breakpoint = "desktop" | "mobile";

interface PersistedPosition {
  x: number;
  y: number;
  breakpoint: Breakpoint;
}

function getBreakpoint(): Breakpoint {
  if (typeof window === "undefined") return "desktop";
  return window.innerWidth >= MOBILE_BREAKPOINT ? "desktop" : "mobile";
}

function getCardSize(bp: Breakpoint): { w: number; h: number } {
  return bp === "desktop"
    ? { w: DESKTOP_W, h: DESKTOP_H }
    : { w: MOBILE_W, h: MOBILE_H };
}

function getDefaultPosition(bp: Breakpoint): { x: number; y: number } {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  const { w, h } = getCardSize(bp);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  // Bottom-right, leaving room for BottomNav on mobile.
  const navReserve = bp === "mobile" ? BOTTOM_NAV_HEIGHT : 0;
  return {
    x: Math.max(0, vw - w - EDGE_MARGIN),
    y: Math.max(0, vh - h - EDGE_MARGIN - navReserve),
  };
}

function clampPosition(
  x: number,
  y: number,
  bp: Breakpoint,
): { x: number; y: number } {
  if (typeof window === "undefined") return { x, y };
  const { w, h } = getCardSize(bp);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const navReserve = bp === "mobile" ? BOTTOM_NAV_HEIGHT : 0;
  const maxX = Math.max(0, vw - w);
  const maxY = Math.max(0, vh - h - navReserve);
  return {
    x: Math.min(Math.max(0, x), maxX),
    y: Math.min(Math.max(0, y), maxY),
  };
}

function readPersistedPosition(bp: Breakpoint): { x: number; y: number } {
  if (typeof window === "undefined" || typeof localStorage === "undefined") {
    return getDefaultPosition(bp);
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultPosition(bp);
    const parsed = JSON.parse(raw) as PersistedPosition;
    if (
      parsed &&
      typeof parsed.x === "number" &&
      typeof parsed.y === "number" &&
      parsed.breakpoint === bp
    ) {
      return clampPosition(parsed.x, parsed.y, bp);
    }
  } catch {
    /* swallow — malformed storage falls back to default */
  }
  return getDefaultPosition(bp);
}

function writePersistedPosition(x: number, y: number, bp: Breakpoint): void {
  if (typeof localStorage === "undefined") return;
  try {
    const rec: PersistedPosition = { x, y, breakpoint: bp };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rec));
  } catch {
    /* storage quota / private-mode — non-fatal */
  }
}

/**
 * If the release point is within SNAP_DISTANCE_PX of a viewport corner,
 * return the corner-anchored position. Otherwise null (= stay put).
 */
function maybeSnapToCorner(
  x: number,
  y: number,
  bp: Breakpoint,
): { x: number; y: number } | null {
  if (typeof window === "undefined") return null;
  const { w, h } = getCardSize(bp);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const navReserve = bp === "mobile" ? BOTTOM_NAV_HEIGHT : 0;

  const corners = {
    tl: { x: EDGE_MARGIN, y: EDGE_MARGIN },
    tr: { x: vw - w - EDGE_MARGIN, y: EDGE_MARGIN },
    bl: { x: EDGE_MARGIN, y: vh - h - EDGE_MARGIN - navReserve },
    br: {
      x: vw - w - EDGE_MARGIN,
      y: vh - h - EDGE_MARGIN - navReserve,
    },
  } as const;

  // Use the card's own top-left as the distance metric — simpler and
  // matches user intuition ("I dragged the card into the corner").
  let best: { x: number; y: number } | null = null;
  let bestDist = SNAP_DISTANCE_PX;
  for (const c of Object.values(corners)) {
    const dx = x - c.x;
    const dy = y - c.y;
    const d = Math.hypot(dx, dy);
    if (d <= bestDist) {
      bestDist = d;
      best = { x: c.x, y: c.y };
    }
  }
  return best;
}

export default function MiniPlayer() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const {
    projectIdOrSlug,
    chapterId,
    chapter,
    status,
    positionMs,
    durationMs,
    currentSegmentId,
    segmentTimings,
    assemblyError,
  } = usePlayerStore();

  // Initialize position lazily so SSR/initial render doesn't touch window.
  const [breakpoint, setBreakpoint] = useState<Breakpoint>(() =>
    getBreakpoint(),
  );
  const [position, setPosition] = useState<{ x: number; y: number }>(() =>
    readPersistedPosition(getBreakpoint()),
  );
  const [isDragging, setIsDragging] = useState(false);
  const [isSnapping, setIsSnapping] = useState(false);

  // Drag bookkeeping refs — avoid re-renders on every pointermove decision.
  const pressTimerRef = useRef<number | null>(null);
  const pressStartRef = useRef<{ x: number; y: number } | null>(null);
  const dragOffsetRef = useRef<{ dx: number; dy: number }>({ dx: 0, dy: 0 });
  const activePointerIdRef = useRef<number | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const cancelledRef = useRef(false);

  // Watch viewport breakpoint + resize.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => {
      const bp = getBreakpoint();
      setBreakpoint(bp);
      setPosition((prev) => {
        const clamped = clampPosition(prev.x, prev.y, bp);
        // If it was clamped, snap to nearest corner for a cleaner layout.
        if (clamped.x !== prev.x || clamped.y !== prev.y) {
          const snap = maybeSnapToCorner(clamped.x, clamped.y, bp);
          return snap ?? clamped;
        }
        return clamped;
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // If breakpoint changed (e.g. rotated device), re-seed from storage.
  useEffect(() => {
    setPosition(readPersistedPosition(breakpoint));
  }, [breakpoint]);

  const clearPressTimer = useCallback(() => {
    if (pressTimerRef.current != null) {
      window.clearTimeout(pressTimerRef.current);
      pressTimerRef.current = null;
    }
  }, []);

  const endDrag = useCallback(
    (releaseX: number, releaseY: number) => {
      const bp = getBreakpoint();
      const clamped = clampPosition(releaseX, releaseY, bp);
      const snap = maybeSnapToCorner(clamped.x, clamped.y, bp);
      const final = snap ?? clamped;
      if (snap) setIsSnapping(true);
      setPosition(final);
      writePersistedPosition(final.x, final.y, bp);
      setIsDragging(false);
      // Clear snap flag after transition completes.
      if (snap) {
        window.setTimeout(() => setIsSnapping(false), 260);
      }
    },
    [],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // Only primary button / touch / pen.
      if (e.button !== undefined && e.button !== 0) return;
      cancelledRef.current = false;
      pressStartRef.current = { x: e.clientX, y: e.clientY };
      activePointerIdRef.current = e.pointerId;
      // Compute offset from card origin → pointer so dragging feels natural.
      const rect = cardRef.current?.getBoundingClientRect();
      if (rect) {
        dragOffsetRef.current = {
          dx: e.clientX - rect.left,
          dy: e.clientY - rect.top,
        };
      }
      clearPressTimer();
      pressTimerRef.current = window.setTimeout(() => {
        // Timer fired — enter drag mode if not cancelled by move/up.
        if (cancelledRef.current) return;
        setIsDragging(true);
        setIsSnapping(false);
        try {
          cardRef.current?.setPointerCapture(e.pointerId);
        } catch {
          /* some browsers / test envs don't support pointer capture */
        }
      }, DRAG_HOLD_MS);
    },
    [clearPressTimer],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (activePointerIdRef.current !== e.pointerId) return;
      if (isDragging) {
        const bp = getBreakpoint();
        const nextX = e.clientX - dragOffsetRef.current.dx;
        const nextY = e.clientY - dragOffsetRef.current.dy;
        setPosition(clampPosition(nextX, nextY, bp));
        return;
      }
      // Pre-drag: cancel if moved too far (user is scrolling, not pressing).
      const start = pressStartRef.current;
      if (!start) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (Math.hypot(dx, dy) > DRAG_MOVE_THRESHOLD_PX) {
        cancelledRef.current = true;
        clearPressTimer();
        pressStartRef.current = null;
        activePointerIdRef.current = null;
      }
    },
    [isDragging, clearPressTimer],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (activePointerIdRef.current !== e.pointerId) return;
      clearPressTimer();
      if (isDragging) {
        endDrag(
          e.clientX - dragOffsetRef.current.dx,
          e.clientY - dragOffsetRef.current.dy,
        );
        try {
          cardRef.current?.releasePointerCapture(e.pointerId);
        } catch {
          /* no-op */
        }
      }
      pressStartRef.current = null;
      activePointerIdRef.current = null;
      cancelledRef.current = false;
    },
    [isDragging, endDrag, clearPressTimer],
  );

  const handlePointerCancel = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (activePointerIdRef.current !== e.pointerId) return;
      clearPressTimer();
      setIsDragging(false);
      pressStartRef.current = null;
      activePointerIdRef.current = null;
      cancelledRef.current = true;
    },
    [clearPressTimer],
  );

  // Cleanup timer on unmount.
  useEffect(() => {
    return () => {
      clearPressTimer();
    };
  }, [clearPressTimer]);

  // --- Render bail -----------------------------------------------------------
  if (!projectIdOrSlug || !chapterId) return null;

  const isPlaying = status === "playing";
  const isBusy = status === "loading" || status === "buffering";
  const isError = status === "error";

  const progress =
    durationMs > 0 ? Math.min(1, Math.max(0, positionMs / durationMs)) : 0;

  let speakerLabel = "Narration";
  if (currentSegmentId && segmentTimings.length) {
    const t = segmentTimings.find((x) => x.segment_id === currentSegmentId);
    if (t?.speaker_name) speakerLabel = t.speaker_name;
  }

  const chapterLabel = chapter?.title
    ? chapter.title
    : chapter?.number != null
      ? `Chapter ${chapter.number}`
      : "Loading…";

  // Initial for the album-art square: first letter of title, or "♪" fallback.
  const badgeInitial =
    chapterLabel && chapterLabel !== "Loading…"
      ? chapterLabel.charAt(0).toUpperCase()
      : "\u266A";

  const fullPlayerHref = `/play/${projectIdOrSlug}?chapter=${chapterId}`;

  const handlePlayPause = () => {
    if (isError) {
      void playerController.loadChapter(projectIdOrSlug, chapterId).then(() => {
        playerController.play();
      });
      return;
    }
    if (isPlaying) playerController.pause();
    else playerController.play();
  };

  const handleClose = async () => {
    playerController.close();
    try {
      await api.upsertPlaybackState(projectIdOrSlug, {
        chapter_id: null,
        current_segment_id: null,
        position_ms: 0,
      });
    } catch {
      /* non-fatal */
    }
    qc.invalidateQueries({ queryKey: ["playback", projectIdOrSlug] });
    qc.invalidateQueries({ queryKey: ["playback"] });
  };

  // Stop button pointer events from bubbling up into the drag-press logic.
  const swallowPointer = (e: React.PointerEvent) => {
    e.stopPropagation();
  };

  // Middle column click → open full player. Guarded so a drag doesn't
  // trigger navigation on release. We intercept at pointerup-time: if a
  // drag was active, don't navigate.
  const handleBodyClick = (e: React.MouseEvent) => {
    if (isDragging) {
      e.preventDefault();
      return;
    }
    // Ignore if the click originated inside an interactive button.
    const target = e.target as HTMLElement;
    if (target.closest("button")) return;
    navigate(fullPlayerHref);
  };

  const { w, h } = getCardSize(breakpoint);

  return (
    <div
      ref={cardRef}
      role="region"
      aria-label="Mini player"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onClick={handleBodyClick}
      className={[
        "fixed z-40 select-none",
        "rounded-2xl shadow-xl backdrop-blur-md",
        "border",
        isError ? "border-error bg-error/10" : "border-accent/40 bg-surface/85",
        isDragging ? "cursor-grabbing" : "cursor-grab",
        // Smooth snap transition; disabled mid-drag for 1:1 tracking.
        isDragging ? "" : isSnapping ? "transition-transform duration-[250ms] ease-out" : "",
      ].join(" ")}
      style={{
        left: 0,
        top: 0,
        width: w,
        height: h,
        transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
        touchAction: "none",
      }}
    >
      <div className="relative flex items-center gap-2 px-2 py-2 h-full">
        {/* Left: small album-art badge. */}
        <div
          className={[
            "shrink-0 aspect-square h-12 w-12 rounded-card",
            "flex items-center justify-center",
            "border",
            isError
              ? "border-error/40 bg-error/10 text-error"
              : "border-accent/30 bg-accent/10 text-accent",
          ].join(" ")}
          aria-hidden="true"
        >
          <span className="text-base font-semibold">{badgeInitial}</span>
        </div>

        {/* Middle: title + speaker. Clickable area → full player (via
            body click handler; no nested <Link> so the drag-press logic
            owns pointer events cleanly). */}
        <div className="flex-1 min-w-0 px-1">
          <div className="text-sm font-medium text-fg truncate">
            {chapterLabel}
          </div>
          <div className="text-xs text-muted truncate">
            {isError ? assemblyError || "Playback error" : speakerLabel}
          </div>
        </div>

        {/* Right: play/pause + close. */}
        <div className="shrink-0 flex items-center gap-1">
          <button
            type="button"
            onClick={handlePlayPause}
            onPointerDown={swallowPointer}
            disabled={isBusy}
            aria-label={isError ? "Retry" : isPlaying ? "Pause" : "Play"}
            className={[
              "h-10 w-10 rounded-full flex items-center justify-center",
              "min-h-tap min-w-tap",
              isError
                ? "bg-error/10 border border-error text-error hover:bg-error/20"
                : isPlaying
                  ? "bg-accent text-bg hover:bg-accent/90"
                  : "bg-accent/15 border border-accent/40 text-accent hover:bg-accent/25",
              isBusy ? "opacity-60 cursor-wait" : "",
            ].join(" ")}
          >
            {isBusy ? (
              <Spinner />
            ) : isError ? (
              <RetryIcon />
            ) : isPlaying ? (
              <PauseIcon />
            ) : (
              <PlayIcon />
            )}
          </button>
          <button
            type="button"
            onClick={handleClose}
            onPointerDown={swallowPointer}
            aria-label="Close player"
            className="h-8 w-8 rounded-full text-muted hover:text-fg
                       hover:bg-surface-2 flex items-center justify-center
                       text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Progress strip: 3px, absolute at bottom, rounded to match card. */}
        <div
          className="absolute inset-x-0 bottom-0 h-[3px] bg-surface-2/60 rounded-b-2xl overflow-hidden"
          aria-hidden="true"
        >
          <div
            className={isError ? "h-full bg-error" : "h-full bg-accent"}
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// --- Icons (inline SVG to avoid adding a dep) --------------------------------

function PlayIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="6" y="5" width="4" height="14" />
      <rect x="14" y="5" width="4" height="14" />
    </svg>
  );
}

function RetryIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <polyline points="3 4 3 10 9 10" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
      className="animate-spin"
    >
      <path d="M21 12a9 9 0 1 1-6.2-8.55" />
    </svg>
  );
}
