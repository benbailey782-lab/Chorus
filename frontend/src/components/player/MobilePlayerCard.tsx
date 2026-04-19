/**
 * MobilePlayerCard — a square card on the mobile player that flips between
 * the cover art (front) and the synced transcript (back) with a 3D rotateY
 * animation.
 *
 * State:
 *   - `flipped` persists in localStorage under `player:mobile-flip`, so
 *     returning users resume on whichever face they last used.
 *   - A one-time hint icon pulses in a corner of the FRONT face until the
 *     user flips at least once, tracked via `player:mobile-flip-hinted`.
 *
 * Mobile-only — the desktop layout keeps its three-column grid untouched.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import CoverArt from "./CoverArt";
import SyncedTextView from "./SyncedTextView";
import type { SegmentTiming } from "../../lib/api";

/**
 * Minimal chapter shape needed for the card header — works for both
 * `Chapter` (nullable title) and `ChapterMeta` (required title).
 */
export interface MobilePlayerCardChapter {
  id: string;
  number: number;
  title: string | null;
}

const FLIP_KEY = "player:mobile-flip";
const HINT_KEY = "player:mobile-flip-hinted";

function loadFlipPref(): boolean {
  try {
    return window.localStorage.getItem(FLIP_KEY) === "1";
  } catch {
    return false;
  }
}

function saveFlipPref(value: boolean): void {
  try {
    window.localStorage.setItem(FLIP_KEY, value ? "1" : "0");
  } catch {
    // ignore quota / disabled storage
  }
}

function loadHintSeen(): boolean {
  try {
    return window.localStorage.getItem(HINT_KEY) === "1";
  } catch {
    return false;
  }
}

function markHintSeen(): void {
  try {
    window.localStorage.setItem(HINT_KEY, "1");
  } catch {
    // ignore
  }
}

interface Props {
  chapter: MobilePlayerCardChapter | null;
  segmentTimings: SegmentTiming[];
  currentSegmentId: string | null;
  onSegmentSeek: (ms: number) => void;
  projectTitle?: string;
}

export default function MobilePlayerCard({
  chapter,
  segmentTimings,
  currentSegmentId,
  onSegmentSeek,
  projectTitle,
}: Props) {
  const [flipped, setFlipped] = useState<boolean>(() => loadFlipPref());
  const [hintSeen, setHintSeen] = useState<boolean>(() => loadHintSeen());
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    saveFlipPref(flipped);
  }, [flipped]);

  const handleCardClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Let interactive children (transcript buttons etc.) handle their own
      // taps without toggling the flip.
      const target = e.target as HTMLElement | null;
      if (target && target.closest("button, a, input, textarea, select")) {
        return;
      }
      setFlipped((prev) => !prev);
      if (!hintSeen) {
        markHintSeen();
        setHintSeen(true);
      }
    },
    [hintSeen],
  );

  const handleKey = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      // Only react when the root itself has focus, not transcript buttons.
      if (e.target !== rootRef.current) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setFlipped((prev) => !prev);
        if (!hintSeen) {
          markHintSeen();
          setHintSeen(true);
        }
      }
    },
    [hintSeen],
  );

  const chapterTitle = chapter?.title ?? undefined;
  const chapterNumber = chapter?.number;

  return (
    <div className="relative w-full [perspective:1200px]">
      <div
        ref={rootRef}
        role="button"
        tabIndex={0}
        aria-label={flipped ? "Show cover art" : "Show transcript"}
        aria-pressed={flipped}
        onClick={handleCardClick}
        onKeyDown={handleKey}
        className={`relative w-full aspect-square rounded-2xl
                    transition-transform duration-[400ms] ease-out
                    [transform-style:preserve-3d]
                    focus:outline-none focus-visible:ring-2 focus-visible:ring-accent
                    ${flipped ? "[transform:rotateY(180deg)]" : ""}`}
      >
        {/* Front face — cover art */}
        <div
          className="absolute inset-0 [backface-visibility:hidden] rounded-2xl overflow-hidden"
          aria-hidden={flipped}
        >
          <CoverArt
            title={projectTitle ?? ""}
            chapterTitle={chapterTitle}
            chapterNumber={chapterNumber}
            ratio="square"
          />
          {!hintSeen && (
            <div
              className="absolute top-2 right-2 h-8 w-8 rounded-full
                         bg-bg/70 backdrop-blur border border-border
                         grid place-items-center text-accent
                         animate-pulse pointer-events-none"
              aria-hidden="true"
              title="Tap to flip"
            >
              <FlipIcon />
            </div>
          )}
        </div>

        {/* Back face — transcript */}
        <div
          className="absolute inset-0 [backface-visibility:hidden]
                     [transform:rotateY(180deg)] overflow-hidden
                     rounded-2xl border border-border bg-surface"
          aria-hidden={!flipped}
        >
          <SyncedTextView
            timings={segmentTimings}
            currentSegmentId={currentSegmentId}
            onSeek={onSegmentSeek}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * Minimal inline refresh/rotate glyph — deliberately small so the hint reads
 * as decoration rather than a competing action.
 */
function FlipIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
    >
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 3v6h-6" />
    </svg>
  );
}
