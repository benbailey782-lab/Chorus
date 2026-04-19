/**
 * Scrubber — chapter timeline with drag-to-seek + segment tick overlay.
 *
 * Uses a native <input type="range"> for accessibility + touch; the visual
 * fill is painted via a CSS gradient computed from positionMs/durationMs.
 *
 * Double-click/tap semantics:
 *   - Double-click on the left half: skip -15s.
 *   - Double-click on the right half: skip +15s.
 *   We listen for `dblclick` which works for both mouse and most touch
 *   browsers (they synthesize dblclick on quick double-taps). Segment seeking
 *   still fires via the normal single-click → onChange path.
 */

import { useState } from "react";

import { playerController } from "../../lib/audioPlayer";
import { usePlayerStore } from "../../stores/playerStore";

function fmt(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0:00";
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function Scrubber() {
  const positionMs = usePlayerStore((s) => s.positionMs);
  const durationMs = usePlayerStore((s) => s.durationMs);
  const segmentTimings = usePlayerStore((s) => s.segmentTimings);

  const [rightMode, setRightMode] = useState<"remaining" | "total">("remaining");

  const pct =
    durationMs > 0 ? Math.min(100, Math.max(0, (positionMs / durationMs) * 100)) : 0;

  const rightLabel =
    rightMode === "remaining"
      ? `-${fmt(Math.max(0, durationMs - positionMs))}`
      : fmt(durationMs);

  function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = Number(e.target.value);
    playerController.seek(val);
  }

  function onDoubleClick(e: React.MouseEvent<HTMLDivElement>) {
    // Decide direction based on which half was clicked relative to the slider
    // bounding box.
    const rect = e.currentTarget.getBoundingClientRect();
    const midX = rect.left + rect.width / 2;
    if (e.clientX < midX) {
      playerController.skip(-15);
    } else {
      playerController.skip(15);
    }
  }

  // Segment tick overlay — one tiny vertical line per boundary so the user
  // has a visual cue of beat density. Skipped when there are a huge number
  // of segments (>400) to avoid DOM bloat.
  const showTicks = segmentTimings.length > 0 && segmentTimings.length <= 400;

  const trackStyle: React.CSSProperties = {
    background: `linear-gradient(to right,
      rgb(78, 200, 190) 0%,
      rgb(78, 200, 190) ${pct}%,
      rgba(255, 255, 255, 0.12) ${pct}%,
      rgba(255, 255, 255, 0.12) 100%)`,
  };

  return (
    <div className="flex items-center gap-3 w-full">
      <span className="text-xs text-muted tabular-nums w-12 text-right">
        {fmt(positionMs)}
      </span>

      <div
        className="relative flex-1 h-6 flex items-center"
        onDoubleClick={onDoubleClick}
      >
        {/* Visual track */}
        <div
          className="absolute inset-x-0 h-1.5 top-1/2 -translate-y-1/2 rounded-full"
          style={trackStyle}
          aria-hidden
        />

        {/* Segment ticks */}
        {showTicks && durationMs > 0 && (
          <div className="absolute inset-x-0 h-3 top-1/2 -translate-y-1/2 pointer-events-none">
            {segmentTimings.map((t) => {
              const left = (t.start_ms / durationMs) * 100;
              if (left <= 0 || left >= 100) return null;
              return (
                <div
                  key={t.segment_id}
                  className="absolute top-0 h-full w-px bg-white/10"
                  style={{ left: `${left}%` }}
                  aria-hidden
                />
              );
            })}
          </div>
        )}

        {/* Actual input — transparent, overlays the visual track */}
        <input
          type="range"
          min={0}
          max={Math.max(durationMs, 1)}
          step={100}
          value={Math.min(positionMs, durationMs || positionMs)}
          onChange={onChange}
          aria-label="Playback position"
          disabled={durationMs === 0}
          className="chorus-scrubber relative z-10 w-full appearance-none bg-transparent
                     focus:outline-none"
        />
      </div>

      <button
        type="button"
        onClick={() => setRightMode((m) => (m === "remaining" ? "total" : "remaining"))}
        aria-label="Toggle remaining / total time"
        className="text-xs text-muted tabular-nums w-14 text-left hover:text-fg"
      >
        {rightLabel}
      </button>
    </div>
  );
}
