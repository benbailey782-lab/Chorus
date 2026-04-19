import type { Segment } from "../../lib/api";

export type SegmentAudioState =
  | "none"
  | "generating"
  | "generated"
  | "approved"
  | "error";

/**
 * Classify a segment's audio-production state for icon rendering + UI gating.
 *
 * Order matters:
 *   - `status === 'generating'` → in flight, show spinner.
 *   - `status === 'error'`      → show error marker regardless of any stale audio_path.
 *   - `approved_at` set         → approved (implicitly means audio exists).
 *   - `audio_path` set          → generated but not yet approved.
 *   - otherwise                 → no audio yet.
 */
export function getSegmentAudioState(seg: Segment): SegmentAudioState {
  if (seg.status === "generating") return "generating";
  if (seg.status === "error") return "error";
  if (seg.approved_at) return "approved";
  if (seg.audio_path) return "generated";
  return "none";
}

export function segmentAudioTitle(state: SegmentAudioState): string {
  switch (state) {
    case "none":
      return "No audio yet";
    case "generating":
      return "Generating…";
    case "generated":
      return "Play generated audio";
    case "approved":
      return "Play approved audio";
    case "error":
      return "Generation error";
  }
}

interface IconProps {
  state: SegmentAudioState;
  size?: number;
  className?: string;
  title?: string;
}

/**
 * Inline SVG icon that represents a segment's audio state. Caller wraps in a
 * button if interactive — this component is purely presentational.
 */
export function SegmentAudioIcon({
  state,
  size = 16,
  className,
  title,
}: IconProps) {
  const resolvedTitle = title ?? segmentAudioTitle(state);

  if (state === "generating") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`animate-spin ${className ?? ""}`}
        aria-label={resolvedTitle}
      >
        <title>{resolvedTitle}</title>
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
    );
  }

  if (state === "error") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#EF4444"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-label={resolvedTitle}
      >
        <title>{resolvedTitle}</title>
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="7" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12" y2="17" />
      </svg>
    );
  }

  if (state === "approved") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#10B981"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-label={resolvedTitle}
      >
        <title>{resolvedTitle}</title>
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }

  // "generated" and "none" both show a play triangle; "none" is muted.
  const stroke = state === "none" ? "#6B6B70" : "currentColor";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={stroke}
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-label={resolvedTitle}
    >
      <title>{resolvedTitle}</title>
      <polygon points="6 4 20 12 6 20 6 4" />
    </svg>
  );
}

/** Format a duration (ms) as `m:ss`. Returns an empty string for null/undefined. */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || ms < 0) return "";
  const totalSeconds = Math.round(ms / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
