/**
 * MobileTranscriptView — a reading-surface transcript for the mobile flip
 * card back face. Shows only three segments at a time (previous/current/next)
 * with typography-driven hierarchy: the current segment is dominant, the
 * previous fades out above, the next fades in below as a teaser.
 *
 * Differs from SyncedTextView (desktop) by design — this view strips borders,
 * duration chips, and narrator labels to feel like prose rather than a data
 * table. Desktop still uses SyncedTextView.
 *
 * Auto-scroll: the current segment is parked ~40% from the top of the
 * container on change. With only three segments rendered there's minimal
 * room to scroll, so we skip the manual-scroll grace window logic from
 * SyncedTextView.
 */

import { useEffect, useMemo, useRef } from "react";

import type { SegmentTiming } from "../../lib/api";

interface Props {
  timings: SegmentTiming[];
  currentSegmentId: string | null;
  onSeek: (ms: number) => void;
}

function isNarratorLike(name: string | null | undefined): boolean {
  if (!name) return true;
  return name.trim().toLowerCase() === "narrator";
}

export default function MobileTranscriptView({
  timings,
  currentSegmentId,
  onSeek,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const currentRef = useRef<HTMLDivElement | null>(null);

  // Derive the current index (and by extension, prev/next) from the id.
  const currentIndex = useMemo(() => {
    if (!currentSegmentId) return -1;
    return timings.findIndex((t) => t.segment_id === currentSegmentId);
  }, [timings, currentSegmentId]);

  const prev = currentIndex > 0 ? timings[currentIndex - 1] : null;
  const current = currentIndex >= 0 ? timings[currentIndex] : null;
  const next =
    currentIndex >= 0 && currentIndex < timings.length - 1
      ? timings[currentIndex + 1]
      : null;

  // Auto-scroll current segment to ~40% from the top of the container.
  useEffect(() => {
    if (!currentRef.current || !containerRef.current) return;
    const container = containerRef.current;
    const el = currentRef.current;
    const containerTop = container.getBoundingClientRect().top;
    const currentTop = el.getBoundingClientRect().top;
    const targetOffset = container.clientHeight * 0.4;
    const delta = currentTop - containerTop - targetOffset;
    container.scrollBy({ top: delta, behavior: "smooth" });
  }, [currentSegmentId]);

  if (timings.length === 0) {
    return (
      <div className="h-full grid place-items-center text-sm text-muted p-6 text-center">
        No segment timings available. Chapter may still be assembling, or
        timings were not persisted.
      </div>
    );
  }

  if (!current) {
    // No current segment selected yet — show a faint nudge rather than the
    // full list. Keeps the surface from looking broken between chapter loads.
    return (
      <div className="h-full grid place-items-center text-sm text-muted p-6 text-center">
        Press play to follow along.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="h-full overflow-y-auto px-5 py-6 relative"
    >
      {/* Previous segment — fading out */}
      {prev && (
        <button
          type="button"
          onClick={() => onSeek(prev.start_ms)}
          className="block w-full text-left text-xs opacity-30 leading-[1.5]
                     text-muted line-clamp-2
                     focus:outline-none focus-visible:opacity-60 transition-opacity"
        >
          {prev.text}
        </button>
      )}

      {/* Current segment — dominant */}
      <div
        ref={currentRef}
        className={`relative ${prev ? "mt-6" : ""}`}
      >
        {!isNarratorLike(current.speaker_name) && (
          <span
            className="absolute top-0 right-0 text-xs opacity-60
                       bg-surface-2 rounded-full px-2 py-0.5
                       pointer-events-none max-w-[50%] truncate"
          >
            {current.speaker_name}
          </span>
        )}
        <p
          className="text-lg sm:text-xl opacity-100 leading-relaxed text-fg
                     whitespace-pre-wrap"
        >
          {current.text}
        </p>
      </div>

      {/* Next segment — teaser fade-in */}
      {next && (
        <button
          type="button"
          onClick={() => onSeek(next.start_ms)}
          className="block w-full text-left text-sm opacity-50 leading-[1.5]
                     text-fg/80 line-clamp-2 mt-6
                     focus:outline-none focus-visible:opacity-80 transition-opacity"
        >
          {next.text}
          <span aria-hidden="true">…</span>
        </button>
      )}
    </div>
  );
}
