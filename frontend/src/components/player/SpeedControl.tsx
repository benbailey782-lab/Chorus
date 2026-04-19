/**
 * SpeedControl — compact mobile pill vs. desktop stepper.
 *
 * Speed list is intentionally broader than the store default (0.5–2.0 in
 * quarter steps) to match what the listener will want while skimming. The
 * controller clamps; the UI just cycles.
 */

import { playerController } from "../../lib/audioPlayer";
import { usePlayerStore } from "../../stores/playerStore";

// Speed ladders — deliberately different orderings.
// Desktop: monotonically ascending (stepper).
const DESKTOP_LADDER = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
// Mobile cycle: starts at 1, jumps through common audiobook speeds before
// dropping to slower speeds.
const MOBILE_CYCLE = [1, 1.25, 1.5, 2, 0.5, 0.75];

interface Props {
  compact?: boolean;
}

export default function SpeedControl({ compact = false }: Props) {
  const speed = usePlayerStore((s) => s.speed);

  if (compact) {
    return <CompactPill speed={speed} />;
  }
  return <DesktopStepper speed={speed} />;
}

function CompactPill({ speed }: { speed: number }) {
  function cycle() {
    const idx = MOBILE_CYCLE.findIndex((v) => Math.abs(v - speed) < 1e-3);
    const next = MOBILE_CYCLE[(idx + 1) % MOBILE_CYCLE.length];
    playerController.setSpeed(next);
  }

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Playback speed ${speed}x (tap to change)`}
      className={`chip min-h-tap text-xs font-medium tabular-nums
                  ${speed !== 1 ? "text-accent border-accent/50" : ""}`}
    >
      {formatSpeed(speed)}x
    </button>
  );
}

function DesktopStepper({ speed }: { speed: number }) {
  function stepBy(dir: -1 | 1) {
    // Clamp to neighbor in DESKTOP_LADDER; tolerate off-ladder speeds (e.g.,
    // 1.1) by snapping to the nearest ladder step first.
    let idx = DESKTOP_LADDER.findIndex((v) => Math.abs(v - speed) < 1e-3);
    if (idx < 0) {
      // off-ladder: find closest index
      idx = 0;
      let best = Infinity;
      DESKTOP_LADDER.forEach((v, i) => {
        const d = Math.abs(v - speed);
        if (d < best) {
          best = d;
          idx = i;
        }
      });
    }
    const next = Math.max(
      0,
      Math.min(DESKTOP_LADDER.length - 1, idx + dir),
    );
    playerController.setSpeed(DESKTOP_LADDER[next]);
  }

  const canDec = speed > DESKTOP_LADDER[0] + 1e-3;
  const canInc = speed < DESKTOP_LADDER[DESKTOP_LADDER.length - 1] - 1e-3;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted uppercase tracking-wider">Speed</span>
      <button
        type="button"
        onClick={() => stepBy(-1)}
        disabled={!canDec}
        aria-label="Slower"
        className="h-9 w-9 rounded-card border border-border bg-surface grid
                   place-items-center hover:bg-surface-2 disabled:opacity-30"
      >
        <span className="text-lg leading-none">−</span>
      </button>
      <span
        className={`min-w-[3.5rem] text-center text-sm tabular-nums font-medium
                    ${speed !== 1 ? "text-accent" : "text-fg"}`}
      >
        {formatSpeed(speed)}x
      </span>
      <button
        type="button"
        onClick={() => stepBy(1)}
        disabled={!canInc}
        aria-label="Faster"
        className="h-9 w-9 rounded-card border border-border bg-surface grid
                   place-items-center hover:bg-surface-2 disabled:opacity-30"
      >
        <span className="text-lg leading-none">+</span>
      </button>
      {Math.abs(speed - 1) > 1e-3 && (
        <button
          type="button"
          onClick={() => playerController.setSpeed(1)}
          className="text-xs text-muted hover:text-fg underline ml-1"
        >
          Reset
        </button>
      )}
    </div>
  );
}

function formatSpeed(s: number): string {
  // 1 → "1.00", 1.25 → "1.25", 0.5 → "0.50". Two decimals, never integer-only.
  return s.toFixed(2);
}
