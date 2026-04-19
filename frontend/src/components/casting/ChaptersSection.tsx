import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Chapter, type Job } from "../../lib/api";
import { useToast } from "../../lib/toast";

const ACTIVE_STATUSES = new Set<Job["status"]>([
  "queued",
  "running",
  "awaiting_response",
]);

// Chapter.segment_count isn't on the list endpoint (only on ChapterMeta /
// GET /api/chapters/{id}). We fall back to the chapter-row `status` column
// (set to "attributed" by the attribute_chapter handler) as the proxy for
// "has segments". Known limitation: the row won't show a real segment
// count — we just know it's been attributed at least once.
type ChapterStatus = "not_started" | "awaiting" | "attributed" | "failed";

interface ChapterLike {
  id: string;
  status: string;
  segment_count?: number;
}

export function resolveChapterStatus(
  chapter: ChapterLike,
  jobs: Job[],
): ChapterStatus {
  const chapterJobs = jobs.filter(
    (j) =>
      j.kind === "attribute_chapter" &&
      (j.payload as { chapter_id?: string } | null)?.chapter_id === chapter.id,
  );
  const active = chapterJobs.find((j) => ACTIVE_STATUSES.has(j.status));
  if (active) return "awaiting";
  if ((chapter.segment_count ?? 0) > 0 || chapter.status === "attributed") {
    return "attributed";
  }
  const lastJob = [...chapterJobs].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  )[0];
  if (lastJob?.status === "failed") return "failed";
  return "not_started";
}

export default function ChaptersSection({
  projectIdOrSlug,
}: {
  projectIdOrSlug: string;
  projectId: string;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();

  const chaptersQ = useQuery({
    queryKey: ["project-chapters", projectIdOrSlug],
    queryFn: () => api.listChapters(projectIdOrSlug),
    enabled: !!projectIdOrSlug,
  });

  const jobsQ = useQuery({
    queryKey: ["project-jobs", projectIdOrSlug],
    queryFn: () => api.listProjectJobs(projectIdOrSlug),
    enabled: !!projectIdOrSlug,
    refetchInterval: (q) => {
      const data = q.state.data as Job[] | undefined;
      if (!data) return 2000;
      return data.some((j) => ACTIVE_STATUSES.has(j.status)) ? 2000 : false;
    },
  });

  const chapters = chaptersQ.data ?? [];
  const jobs = jobsQ.data ?? [];

  const statuses = useMemo(
    () => new Map(chapters.map((c) => [c.id, resolveChapterStatus(c, jobs)])),
    [chapters, jobs],
  );

  const attributedCount = useMemo(
    () =>
      chapters.reduce(
        (n, c) => (statuses.get(c.id) === "attributed" ? n + 1 : n),
        0,
      ),
    [chapters, statuses],
  );
  const totalCount = chapters.length;
  const unattributedCount = useMemo(
    () =>
      chapters.reduce(
        (n, c) =>
          statuses.get(c.id) === "not_started" ||
          statuses.get(c.id) === "failed"
            ? n + 1
            : n,
        0,
      ),
    [chapters, statuses],
  );
  const hasActiveAttributeJob = useMemo(
    () =>
      jobs.some(
        (j) =>
          j.kind === "attribute_chapter" && ACTIVE_STATUSES.has(j.status),
      ),
    [jobs],
  );

  const attributeAll = useMutation({
    mutationFn: () => api.attributeAllChapters(projectIdOrSlug),
    onSuccess: (res) => {
      toast({
        kind: "success",
        message: `Queued ${res.chapter_count} chapter${res.chapter_count === 1 ? "" : "s"} for attribution.`,
      });
      qc.invalidateQueries({ queryKey: ["project-jobs", projectIdOrSlug] });
    },
    onError: (err) => {
      toast({
        kind: "error",
        message: (err as Error).message || "Failed to queue attribute-all.",
      });
    },
  });

  const attributeOne = useMutation({
    mutationFn: (chapterId: string) => api.attributeChapter(chapterId),
    onSuccess: () => {
      toast({ kind: "success", message: "Chapter queued for attribution." });
      qc.invalidateQueries({ queryKey: ["project-jobs", projectIdOrSlug] });
    },
    onError: (err) => {
      toast({
        kind: "error",
        message: (err as Error).message || "Failed to queue attribution.",
      });
    },
  });

  const progressPct =
    totalCount === 0 ? 0 : Math.round((attributedCount / totalCount) * 100);

  const attributeAllLabel = (() => {
    if (unattributedCount === 0) return "All attributed";
    if (hasActiveAttributeJob) return "Jobs in flight…";
    return `Attribute all (${unattributedCount} remaining)`;
  })();
  const attributeAllDisabled =
    unattributedCount === 0 ||
    hasActiveAttributeJob ||
    attributeAll.isPending;

  return (
    <section className="mt-8 space-y-3">
      {/* Header row ------------------------------------------------- */}
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <h2 className="font-display text-xl">Chapters</h2>
        <div className="flex items-center gap-3 min-w-[14rem]">
          <span className="text-xs text-muted whitespace-nowrap">
            {attributedCount} of {totalCount} chapters attributed
          </span>
          <div
            className="h-1.5 w-32 rounded-full bg-border overflow-hidden"
            aria-hidden="true"
          >
            <div
              className="h-full bg-accent transition-[width] duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Attribute-all button -------------------------------------- */}
      <div>
        <button
          type="button"
          className="btn-primary"
          disabled={attributeAllDisabled}
          onClick={() => attributeAll.mutate()}
        >
          {attributeAllLabel}
        </button>
      </div>

      {/* Chapter list ---------------------------------------------- */}
      {chaptersQ.isLoading ? (
        <p className="text-muted text-sm">Loading chapters…</p>
      ) : chaptersQ.isError ? (
        <p className="text-error text-sm">
          {(chaptersQ.error as Error).message}
        </p>
      ) : chapters.length === 0 ? (
        <p className="text-muted text-sm">
          No chapters yet. Ingest a source file to get started.
        </p>
      ) : (
        <ul className="space-y-2">
          {chapters.map((ch) => (
            <ChapterRow
              key={ch.id}
              chapter={ch}
              status={statuses.get(ch.id) ?? "not_started"}
              onAttribute={() => attributeOne.mutate(ch.id)}
              onReview={() =>
                navigate(`/project/${projectIdOrSlug}/chapters/${ch.id}`)
              }
              pending={attributeOne.isPending}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ChapterRow({
  chapter,
  status,
  onAttribute,
  onReview,
  pending,
}: {
  chapter: Chapter;
  status: ChapterStatus;
  onAttribute: () => void;
  onReview: () => void;
  pending: boolean;
}) {
  const title = chapter.title || `Chapter ${chapter.number}`;
  const wordCount = chapter.word_count ?? 0;

  return (
    <li>
      <div
        className="card flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3
                   py-3 px-4 transition-colors hover:border-accent/40"
      >
        {/* Top line (mobile) / left side (desktop): number + title + words */}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 min-w-0">
            <span className="text-xs text-muted font-mono shrink-0">
              {chapter.number}
            </span>
            <span className="font-medium truncate">{title}</span>
          </div>
          <div className="text-xs text-muted">
            {wordCount.toLocaleString()} words
          </div>
        </div>

        {/* Bottom line (mobile) / right side (desktop): segs + chip + action */}
        <div className="flex items-center gap-2 justify-between sm:justify-end">
          <div className="flex items-center gap-2">
            <SegmentBadge chapter={chapter} status={status} />
            <StatusChip status={status} />
          </div>
          <ActionButton
            status={status}
            onAttribute={onAttribute}
            onReview={onReview}
            pending={pending}
          />
        </div>
      </div>
    </li>
  );
}

function SegmentBadge({
  chapter,
  status,
}: {
  chapter: Chapter;
  status: ChapterStatus;
}) {
  // Chapter list endpoint doesn't carry segment_count today. When attributed,
  // show a generic "attributed" indicator in place of the per-chapter count.
  const count = (chapter as unknown as { segment_count?: number }).segment_count;
  if (status !== "attributed") return null;
  if (typeof count === "number" && count > 0) {
    return (
      <span className="chip text-[10px] uppercase tracking-wider text-muted">
        {count} segments
      </span>
    );
  }
  return null;
}

function StatusChip({ status }: { status: ChapterStatus }) {
  switch (status) {
    case "awaiting":
      return (
        <span
          className="chip text-[10px] uppercase tracking-wider
                     border-warn/40 bg-warn/10 text-warn
                     inline-flex items-center gap-1.5"
        >
          <span
            aria-hidden="true"
            className="inline-block w-1.5 h-1.5 rounded-full bg-warn animate-pulse"
          />
          Attributing…
        </span>
      );
    case "attributed":
      return (
        <span
          className="chip text-[10px] uppercase tracking-wider
                     border-accent/40 bg-accent/10 text-accent"
        >
          Attributed
        </span>
      );
    case "failed":
      return (
        <span
          className="chip text-[10px] uppercase tracking-wider
                     border-error/40 bg-error/10 text-error"
        >
          Failed
        </span>
      );
    case "not_started":
    default:
      return (
        <span className="chip text-[10px] uppercase tracking-wider text-muted">
          Not attributed
        </span>
      );
  }
}

function ActionButton({
  status,
  onAttribute,
  onReview,
  pending,
}: {
  status: ChapterStatus;
  onAttribute: () => void;
  onReview: () => void;
  pending: boolean;
}) {
  if (status === "awaiting") return null;
  if (status === "attributed") {
    return (
      <button
        type="button"
        className="btn-ghost min-h-tap text-xs"
        onClick={onReview}
      >
        Review
      </button>
    );
  }
  const label = status === "failed" ? "Retry" : "Attribute";
  return (
    <button
      type="button"
      className="btn-surface min-h-tap text-xs"
      onClick={onAttribute}
      disabled={pending}
    >
      {label}
    </button>
  );
}
