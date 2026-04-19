import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { playerController } from "../../lib/audioPlayer";
import { usePlayerStore } from "../../stores/playerStore";

/**
 * Persistent mini-player strip (Phase 6, §15.X).
 *
 * Visible only when the store has a chapter loaded. Rendered by `<Layout>`
 * so it stays mounted across route changes — audio keeps playing while the
 * user browses `/library`, `/voices`, `/player`, etc. Hidden on the full
 * player route by Layout itself.
 *
 * Layout:
 *   [ cover | title / speaker (click → full player) ]
 *   [ play/pause button (center) ]
 *   [ close × ]
 *   [ 3px progress strip absolute at bottom-0 ]
 *
 * Close soft-clears the playback row per decision 7 (chapter_id → null);
 * does NOT delete history so the user can resume from any chapter by
 * opening a project.
 */
export default function MiniPlayer() {
  const qc = useQueryClient();
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

  // Render nothing until the store has both identity keys. Prevents an
  // empty strip from showing between `/play/...` mount and the first
  // store update.
  if (!projectIdOrSlug || !chapterId) return null;

  const isPlaying = status === "playing";
  const isBusy = status === "loading" || status === "buffering";
  const isError = status === "error";

  const progress =
    durationMs > 0 ? Math.min(1, Math.max(0, positionMs / durationMs)) : 0;

  // Find current speaker for the subtitle line — segmentTimings is the
  // source of truth set by the controller.
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

  const fullPlayerHref = `/play/${projectIdOrSlug}?chapter=${chapterId}`;

  const handlePlayPause = () => {
    if (isError) {
      // Retry: attempt to reload the chapter from store values.
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
    // Soft-clear the DB row (decision 7). If this fails, log + swallow —
    // stale row will just get overwritten on the next play.
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

  return (
    <div
      // Fixed above BottomNav (4rem = 64px). Safe-area padding pushes
      // above the iOS home indicator when BottomNav is hidden (≥md).
      role="region"
      aria-label="Mini player"
      className={[
        "fixed inset-x-0 bottom-16 z-30",
        "border-t border-border",
        isError ? "bg-error/10" : "bg-surface/95",
        "backdrop-blur",
        "md:bottom-0",
      ].join(" ")}
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      <div className="relative max-w-5xl mx-auto flex items-center gap-2 px-2 py-2 md:px-4">
        {/* Left: clickable identity block → full player. */}
        <Link
          to={fullPlayerHref}
          className="flex items-center gap-3 flex-1 min-w-0 rounded-card
                     hover:bg-surface-2 active:bg-surface-2 transition-colors
                     px-1 py-1"
          aria-label="Open full player"
        >
          {/* Placeholder cover. Keeps MiniPlayer self-contained — no
              chapter-art fetching here. */}
          <div
            className="h-12 w-12 shrink-0 rounded-card bg-surface-2 border border-border
                       flex items-center justify-center"
            aria-hidden="true"
          >
            <span className="block h-2 w-2 rounded-full bg-accent" />
          </div>
          <div className="min-w-0">
            <div className="text-sm text-fg truncate">{chapterLabel}</div>
            <div className="text-xs text-muted truncate">
              {isError
                ? assemblyError || "Playback error"
                : speakerLabel}
            </div>
          </div>
        </Link>

        {/* Center: play/pause. */}
        <button
          type="button"
          onClick={handlePlayPause}
          disabled={isBusy}
          aria-label={
            isError ? "Retry" : isPlaying ? "Pause" : "Play"
          }
          className={[
            "shrink-0 h-12 w-12 rounded-full border flex items-center justify-center",
            "min-h-tap min-w-tap",
            isError
              ? "border-error text-error hover:bg-error/10"
              : "border-accent text-accent hover:bg-accent/10",
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

        {/* Right: close. */}
        <button
          type="button"
          onClick={handleClose}
          aria-label="Close player"
          className="shrink-0 h-8 w-8 rounded-full text-muted hover:text-fg
                     hover:bg-surface-2 flex items-center justify-center text-xl leading-none"
        >
          ×
        </button>

        {/* Progress strip: absolute-bottom, spans full width. Thin, accent fill. */}
        <div
          className="absolute inset-x-0 bottom-0 h-[3px] bg-surface-2"
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
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="6" y="5" width="4" height="14" />
      <rect x="14" y="5" width="4" height="14" />
    </svg>
  );
}

function RetryIcon() {
  return (
    <svg
      width="20"
      height="20"
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
      width="20"
      height="20"
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
