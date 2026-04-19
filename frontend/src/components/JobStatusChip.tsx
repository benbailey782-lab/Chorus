import type { JobStatus } from "../lib/api";

const LABELS: Record<JobStatus, string> = {
  queued: "queued",
  running: "running",
  awaiting_response: "awaiting Claude Code",
  complete: "complete",
  failed: "failed",
};

const CLASSES: Record<JobStatus, string> = {
  queued: "text-muted border-border",
  running: "text-accent border-accent/40",
  awaiting_response: "text-warn border-warn/40",
  complete: "text-success border-success/40",
  failed: "text-error border-error/40",
};

export default function JobStatusChip({ status }: { status: JobStatus }) {
  return (
    <span
      className={`chip text-[10px] uppercase tracking-wider ${CLASSES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
