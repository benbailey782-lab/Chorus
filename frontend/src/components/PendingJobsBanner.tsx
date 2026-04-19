import { useQuery } from "@tanstack/react-query";

import JobStatusChip from "./JobStatusChip";
import { api, type Job } from "../lib/api";

const ACTIVE_STATUSES = new Set<Job["status"]>(["queued", "running", "awaiting_response"]);

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

  return (
    <div className="space-y-2">
      {active.map((job) => (
        <div
          key={job.id}
          className="card border-warn/40 bg-warn/10 px-3 py-2 text-sm"
        >
          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block w-2 h-2 rounded-full bg-warn animate-pulse"
            />
            <span className="font-medium text-fg">
              {relativeKind(job.kind)}
            </span>
            <JobStatusChip status={job.status} />
          </div>
          <div className="mt-1 text-xs text-muted">
            {job.status === "awaiting_response"
              ? <>Waiting on Claude Code. Check <code className="font-mono">data/llm_queue/pending/request_{job.id}.md</code> — the companion session should pick it up and drop the response at <code className="font-mono">data/llm_queue/responses/response_{job.id}.json</code>.</>
              : job.message ?? "Working…"}
          </div>
        </div>
      ))}
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
