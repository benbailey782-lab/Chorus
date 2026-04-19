/**
 * ChapterList — sidebar list of project chapters with assembly status chip.
 *
 * Strategy note (per Commit 5 spec): we fire one assembly-status query per
 * chapter with a 30s stale window. For typical projects (20–70 chapters)
 * this is fine; for very large corpora (200+) Phase 7 can swap in a batched
 * endpoint. The query uses `enabled: !!chapterId` so unmounted rows don't
 * fetch.
 */

import { useQueries } from "@tanstack/react-query";

import { api, type Chapter } from "../../lib/api";
import { usePlayerStore } from "../../stores/playerStore";

interface Props {
  chapters: Chapter[];
  onSelect: (chapterId: string) => void;
}

export default function ChapterList({ chapters, onSelect }: Props) {
  const currentId = usePlayerStore((s) => s.chapterId);

  const statusQueries = useQueries({
    queries: chapters.map((c) => ({
      queryKey: ["chapter-assembly-status", c.id],
      queryFn: () => api.chapterAssemblyStatus(c.id),
      staleTime: 30_000,
      enabled: !!c.id,
      // Don't retry noisily on 404s etc — the row just shows "—".
      retry: false,
    })),
  });

  return (
    <nav aria-label="Chapters" className="h-full overflow-y-auto">
      <ul className="divide-y divide-border">
        {chapters.map((c, i) => {
          const q = statusQueries[i];
          const status = q.data;
          const isCurrent = c.id === currentId;
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                className={`w-full text-left px-3 py-2.5 transition-colors
                            focus:outline-none focus-visible:bg-surface-2
                            ${
                              isCurrent
                                ? "border-l-2 border-accent bg-accent/10"
                                : "border-l-2 border-transparent hover:bg-surface-2"
                            }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-[10px] uppercase tracking-wider text-muted">
                      Chapter {c.number}
                    </div>
                    <div
                      className={`text-sm truncate ${
                        isCurrent ? "text-fg font-medium" : "text-fg/90"
                      }`}
                    >
                      {c.title || `Chapter ${c.number}`}
                    </div>
                  </div>
                  <StatusChip status={status} />
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function StatusChip({
  status,
}: {
  status:
    | { ready: boolean; missing_segments: string[]; assembling: boolean }
    | undefined;
}) {
  if (!status) {
    return <span className="text-[10px] text-muted shrink-0">—</span>;
  }
  if (status.ready) {
    return (
      <span
        className="text-[10px] uppercase tracking-wider text-accent shrink-0"
        title="Assembled and ready"
      >
        ready
      </span>
    );
  }
  if (status.missing_segments.length > 0) {
    return (
      <span
        className="text-[10px] uppercase tracking-wider text-warn shrink-0"
        title={`${status.missing_segments.length} segments missing audio`}
      >
        missing
      </span>
    );
  }
  if (status.assembling) {
    return (
      <span
        className="text-[10px] uppercase tracking-wider text-muted shrink-0"
        title="Assembling now"
      >
        …
      </span>
    );
  }
  return (
    <span
      className="text-[10px] uppercase tracking-wider text-muted shrink-0"
      title="Not yet assembled"
    >
      not yet
    </span>
  );
}
