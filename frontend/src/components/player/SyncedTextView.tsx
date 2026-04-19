/**
 * SyncedTextView — scrolling transcript of the current chapter with the
 * current segment highlighted. Click a segment to seek to its start.
 *
 * Auto-scroll rule: when the current segment changes we scroll it into the
 * middle of the viewport UNLESS the user has scrolled the view manually in
 * the last 5 seconds. That keeps a cooperative "I want to read ahead" mode
 * from being constantly yanked back to the cursor.
 */

import { useEffect, useRef } from "react";

import type { SegmentTiming } from "../../lib/api";

interface Props {
  timings: SegmentTiming[];
  currentSegmentId: string | null;
  onSeek: (ms: number) => void;
}

const MANUAL_SCROLL_GRACE_MS = 5000;

export default function SyncedTextView({
  timings,
  currentSegmentId,
  onSeek,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const lastManualScrollAt = useRef<number>(0);
  // Tracks programmatic scrolls so scrollIntoView doesn't trigger the
  // manual-scroll grace window. React's onScroll fires synchronously for both
  // manual and programmatic scrolls, so we suppress the next N scroll events
  // after we call scrollIntoView ourselves.
  const suppressNextScroll = useRef<number>(0);

  // Auto-scroll effect on currentSegmentId change.
  useEffect(() => {
    if (!currentSegmentId) return;
    const el = document.getElementById(`seg-${currentSegmentId}`);
    if (!el) return;
    const now = Date.now();
    if (now - lastManualScrollAt.current < MANUAL_SCROLL_GRACE_MS) return;
    suppressNextScroll.current = 2; // scrollIntoView usually triggers 1–2 scroll events
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [currentSegmentId]);

  function onScroll() {
    if (suppressNextScroll.current > 0) {
      suppressNextScroll.current -= 1;
      return;
    }
    lastManualScrollAt.current = Date.now();
  }

  if (timings.length === 0) {
    return (
      <div className="h-full grid place-items-center text-sm text-muted p-6 text-center">
        No segment timings available. Chapter may still be assembling, or
        timings were not persisted.
      </div>
    );
  }

  // Dedupe speaker labels — only show when speaker changes from previous row.
  return (
    <div
      ref={containerRef}
      onScroll={onScroll}
      className="h-full overflow-y-auto px-4 py-3 space-y-1"
    >
      {timings.map((t, i) => {
        const prev = i > 0 ? timings[i - 1] : null;
        const showSpeaker =
          t.speaker_name && (!prev || prev.speaker_name !== t.speaker_name);
        const isCurrent = t.segment_id === currentSegmentId;
        const durationSec = (t.duration_ms / 1000).toFixed(1);

        return (
          <div key={t.segment_id}>
            {showSpeaker && (
              <div className="text-[10px] uppercase tracking-wider text-muted mt-3 mb-1">
                {t.speaker_name}
              </div>
            )}
            <button
              type="button"
              id={`seg-${t.segment_id}`}
              onClick={() => onSeek(t.start_ms)}
              className={`w-full text-left rounded-card px-3 py-2 transition-colors
                          focus:outline-none focus-visible:ring-1 focus-visible:ring-accent
                          ${
                            isCurrent
                              ? "bg-accent/15 border-l-2 border-accent text-fg text-[0.95rem]"
                              : "border-l-2 border-transparent hover:bg-surface-2 text-fg/85"
                          }`}
            >
              <div className="flex gap-3 items-baseline">
                <p className="flex-1 whitespace-pre-wrap">{t.text_preview}</p>
                <span className="text-[10px] text-muted tabular-nums shrink-0">
                  {durationSec}s
                </span>
              </div>
            </button>
          </div>
        );
      })}
    </div>
  );
}
