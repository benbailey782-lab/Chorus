import type {
  ChapterGenerationStatus,
  GenerationEstimate,
} from "../../lib/api";

interface Props {
  status: ChapterGenerationStatus;
  estimate: GenerationEstimate | undefined;
}

/**
 * Estimate remaining seconds by scaling the original estimate by the fraction
 * of segments still outstanding (pending + generating). Returns null when we
 * cannot estimate (missing estimate / total).
 */
function estimateRemainingSeconds(
  status: ChapterGenerationStatus,
  estimate: GenerationEstimate | undefined,
): number | null {
  if (!estimate || status.total <= 0) return null;
  const remaining = status.pending + status.generating;
  if (remaining <= 0) return 0;
  const ratio = remaining / status.total;
  return Math.max(0, Math.round(estimate.seconds * ratio));
}

function formatRemaining(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds <= 0) return "wrapping up";
  if (seconds < 60) return `~${seconds}s remaining`;
  const mins = Math.round(seconds / 60);
  return `~${mins}m remaining`;
}

export default function GenerationProgressBar({ status, estimate }: Props) {
  const done = status.generated + status.approved;
  const total = status.total;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const remaining = estimateRemainingSeconds(status, estimate);
  const remainingLabel = formatRemaining(remaining);

  return (
    <div
      className="border-b border-border bg-surface-2/40 px-4 py-2 flex items-center gap-3 text-xs"
      role="status"
      aria-label="Generation progress"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono text-fg">
            {done} of {total}
          </span>
          {remainingLabel && (
            <span className="text-muted">· {remainingLabel}</span>
          )}
          {status.error > 0 && (
            <span
              className="chip text-[10px] uppercase tracking-wider"
              style={{ color: "#EF4444", borderColor: "#EF4444" }}
              title={`${status.error} segment${status.error === 1 ? "" : "s"} failed`}
            >
              {status.error} failed
            </span>
          )}
        </div>
        <div className="mt-1 h-1.5 w-full rounded-full bg-border/60 overflow-hidden">
          <div
            className="h-full bg-accent transition-[width] duration-500"
            style={{ width: `${pct}%` }}
            aria-hidden="true"
          />
        </div>
      </div>
    </div>
  );
}
