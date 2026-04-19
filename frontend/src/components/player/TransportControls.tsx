/**
 * TransportControls — the primary playback button cluster.
 *
 * Reads from `usePlayerStore` (status + assemblyError) and calls the
 * controller singleton for side effects. The controller owns the audio
 * element; this component is purely presentational + dispatch.
 */

import { playerController } from "../../lib/audioPlayer";
import { usePlayerStore } from "../../stores/playerStore";
import type { Chapter } from "../../lib/api";

interface Props {
  chapters: Chapter[];
  /** Compact button sizes on mobile bottom dock; desktop uses larger. */
  compact?: boolean;
}

export default function TransportControls({ chapters, compact = false }: Props) {
  const status = usePlayerStore((s) => s.status);
  const chapterId = usePlayerStore((s) => s.chapterId);
  const projectIdOrSlug = usePlayerStore((s) => s.projectIdOrSlug);
  const assemblyError = usePlayerStore((s) => s.assemblyError);

  const idx = chapters.findIndex((c) => c.id === chapterId);
  const atFirst = idx <= 0;
  const atLast = idx < 0 || idx >= chapters.length - 1;

  const isPlaying = status === "playing";
  const isLoading = status === "loading" || status === "buffering";
  const isError = status === "error";
  const isFinished = status === "finished";

  const playPauseSize = compact ? "h-16 w-16" : "h-14 w-14";
  const skipSize = compact ? "h-12 w-12" : "h-11 w-11";

  function togglePlay() {
    if (isPlaying) playerController.pause();
    else playerController.play();
  }

  function retry() {
    if (projectIdOrSlug && chapterId) {
      void playerController.loadChapter(projectIdOrSlug, chapterId);
    }
  }

  function replay() {
    // Seek to zero + play the current chapter. The 'playing' status comes
    // from the audio element's 'playing' event (see audioPlayer.ts) which
    // clears the 'finished' state naturally.
    playerController.seek(0);
    playerController.play();
  }

  if (isFinished) {
    return (
      <div className="flex flex-col items-center gap-3">
        <div className="chip border-accent/40 bg-accent/10 text-accent text-xs max-w-md text-center">
          Book complete — thanks for listening.
        </div>
        <button type="button" className="btn-primary text-sm" onClick={replay}>
          Replay chapter
        </button>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center gap-2">
        <div className="chip border-error/40 bg-error/10 text-error text-xs max-w-md text-center">
          {assemblyError ?? "Playback error"}
        </div>
        <button type="button" className="btn-surface text-sm" onClick={retry}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center gap-3">
      <IconButton
        label="Previous chapter"
        onClick={() => void playerController.previous(chapters)}
        disabled={atFirst}
        size={skipSize}
      >
        <PrevIcon />
      </IconButton>

      <IconButton
        label="Skip back 15 seconds"
        onClick={() => playerController.skip(-15)}
        size={skipSize}
      >
        <SkipBackIcon />
      </IconButton>

      <button
        type="button"
        aria-label={isPlaying ? "Pause" : "Play"}
        onClick={togglePlay}
        disabled={isLoading}
        className={`${playPauseSize} rounded-full bg-accent text-accent-fg
                    grid place-items-center hover:bg-accent/90
                    disabled:opacity-60 disabled:cursor-wait transition-colors`}
      >
        {isLoading ? (
          <Spinner />
        ) : isPlaying ? (
          <PauseIcon large />
        ) : (
          <PlayIcon large />
        )}
      </button>

      <IconButton
        label="Skip forward 15 seconds"
        onClick={() => playerController.skip(15)}
        size={skipSize}
      >
        <SkipForwardIcon />
      </IconButton>

      <IconButton
        label="Next chapter"
        onClick={() => void playerController.next(chapters)}
        disabled={atLast}
        size={skipSize}
      >
        <NextIcon />
      </IconButton>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function IconButton({
  label,
  onClick,
  disabled,
  size,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  size: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`${size} rounded-full bg-surface border border-border
                  text-fg grid place-items-center hover:bg-surface-2
                  disabled:opacity-30 disabled:cursor-not-allowed transition-colors`}
    >
      {children}
    </button>
  );
}

function PlayIcon({ large = false }: { large?: boolean }) {
  const s = large ? 26 : 18;
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon({ large = false }: { large?: boolean }) {
  const s = large ? 26 : 18;
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}

function PrevIcon() {
  return (
    <svg width={20} height={20} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6 6h2v12H6zM9 12l10-6v12z" />
    </svg>
  );
}

function NextIcon() {
  return (
    <svg width={20} height={20} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M16 6h2v12h-2zM5 6v12l10-6z" />
    </svg>
  );
}

function SkipBackIcon() {
  return (
    <svg
      width={22}
      height={22}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <polyline points="3 4 3 10 9 10" />
      <text
        x="12"
        y="16"
        fontSize="9"
        fontFamily="inherit"
        fill="currentColor"
        stroke="none"
        textAnchor="middle"
      >
        15
      </text>
    </svg>
  );
}

function SkipForwardIcon() {
  return (
    <svg
      width={22}
      height={22}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <polyline points="21 4 21 10 15 10" />
      <text
        x="12"
        y="16"
        fontSize="9"
        fontFamily="inherit"
        fill="currentColor"
        stroke="none"
        textAnchor="middle"
      >
        15
      </text>
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      width={24}
      height={24}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      className="animate-spin"
      aria-hidden
    >
      <path d="M21 12a9 9 0 1 1-6.2-8.55" />
    </svg>
  );
}
