import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import JobStatusChip from "./JobStatusChip";
import { api, type Job } from "../lib/api";

const ACTIVE_STATUSES = new Set<Job["status"]>(["queued", "running", "awaiting_response"]);
const COLLAPSE_THRESHOLD = 5;

function relativeKind(kind: string): string {
  return kind.replace(/_/g, " ");
}

export default function PendingJobsBanner({
  projectIdOrSlug,
}: {
  projectIdOrSlug: string;
}) {
  const jobs = useQuery({
    queryKey: ["project-jobs", projectIdOrSlug],
    queryFn: () => api.listProjectJobs(projectIdOrSlug),
    refetchInterval: (q) => {
      const data = q.state.data as Job[] | undefined;
      if (!data) return 2000;
      return data.some((j) => ACTIVE_STATUSES.has(j.status)) ? 2000 : false;
    },
  });

  const active = (jobs.data ?? []).filter((j) => ACTIVE_STATUSES.has(j.status));
  const recentlyFailed = (jobs.data ?? []).filter((j) => j.status === "failed").slice(0, 3);

  if (active.length === 0 && recentlyFailed.length === 0) return null;

  // Group active jobs by kind. When a group has ≥ COLLAPSE_THRESHOLD, render
  // it as a single summary row with an "expand" toggle instead of spamming
  // the banner with 30+ identical awaiting-response cards (common for
  // attribute-all across an AGoT-scale book).
  const byKind = new Map<string, Job[]>();
  for (const j of active) {
    const list = byKind.get(j.kind) ?? [];
    list.push(j);
    byKind.set(j.kind, list);
  }

  return (
    <div className="space-y-2">
      {[...byKind.entries()].map(([kind, group]) =>
        group.length >= COLLAPSE_THRESHOLD ? (
          <CollapsedGroup key={kind} kind={kind} jobs={group} />
        ) : (
          group.map((job) => <ActiveJobCard key={job.id} job={job} />)
        ),
      )}
      {recentlyFailed.map((job) => (
        <div
          key={job.id}
          className="card border-error/40 bg-error/10 px-3 py-2 text-sm"
        >
          <div className="flex items-center gap-2">
            <span className="font-medium text-fg">{relativeKind(job.kind)}</span>
            <JobStatusChip status={job.status} />
          </div>
          <div className="mt-1 text-xs text-error whitespace-pre-wrap break-words">
            {job.error ?? "Job failed without an error message."}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActiveJobCard({ job }: { job: Job }) {
  return (
    <div className="card border-warn/40 bg-warn/10 px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block w-2 h-2 rounded-full bg-warn animate-pulse"
        />
        <span className="font-medium text-fg">{relativeKind(job.kind)}</span>
        <JobStatusChip status={job.status} />
      </div>
      <div className="mt-1 text-xs text-muted">
        {job.status === "awaiting_response" ? (
          <>
            Waiting on Claude Code. Check{" "}
            <code className="font-mono">
              data/llm_queue/pending/request_{job.id}.md
            </code>
            .
          </>
        ) : (
          job.message ?? "Working…"
        )}
      </div>
    </div>
  );
}

function CollapsedGroup({ kind, jobs }: { kind: string; jobs: Job[] }) {
  const [expanded, setExpanded] = useState(false);
  const awaiting = jobs.filter((j) => j.status === "awaiting_response").length;
  const running = jobs.filter((j) => j.status === "running").length;
  const queued = jobs.filter((j) => j.status === "queued").length;

  return (
    <div className="card border-warn/40 bg-warn/10 px-3 py-2 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          aria-hidden
          className="inline-block w-2 h-2 rounded-full bg-warn animate-pulse"
        />
        <span className="font-medium text-fg">
          {jobs.length} × {relativeKind(kind)}
        </span>
        <span className="text-xs text-muted">
          {awaiting ? `${awaiting} awaiting` : null}
          {awaiting && (running || queued) ? " · " : null}
          {running ? `${running} running` : null}
          {running && queued ? " · " : null}
          {queued ? `${queued} queued` : null}
        </span>
        <button
          type="button"
          className="ml-auto text-xs text-accent hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "collapse" : "show all"}
        </button>
      </div>
      <div className="mt-1 text-xs text-muted">
        Waiting on Claude Code — the companion session processes these one at
        a time. Pending requests are under{" "}
        <code className="font-mono">data/llm_queue/pending/</code>.
      </div>
      {expanded && (
        <ul className="mt-2 space-y-1 max-h-64 overflow-auto pr-1">
          {jobs.map((j) => (
            <li
              key={j.id}
              className="flex items-center gap-2 text-xs text-muted"
            >
              <JobStatusChip status={j.status} />
              <code className="font-mono truncate">{j.id}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
