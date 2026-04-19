import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";

import { api, type PlaybackState, type Project } from "../lib/api";
import { playerController } from "../lib/audioPlayer";

/**
 * Player tab (Phase 6, commit 6).
 *
 * Two sections:
 *   A. Continue Listening — projects with a non-null `chapter_id` playback
 *      row, sorted by `updated_at` desc. Each card resumes playback.
 *   B. All Projects — flat list, tap Play to open the full Player which
 *      resolves chapter via playback state or first chapter.
 *
 * Playback state is fetched per-project with `useQueries`. That's N+1
 * calls at load, but the lists are typically small (personal project) and
 * the endpoint is a single-row SELECT. If this becomes a problem, replace
 * with a `GET /api/playback` bulk endpoint — deferred.
 */
export default function PlayerTab() {
  const projectsQ = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const projects = projectsQ.data ?? [];

  const playbackQueries = useQueries({
    queries: projects.map((p) => ({
      queryKey: ["playback", p.id],
      queryFn: () => api.getPlaybackState(p.id),
      // Playback state is cheap — refetch eagerly so the Continue row
      // reflects reality after closing/reopening the mini-player.
      staleTime: 10_000,
    })),
  });

  // Merge playback state with project data. Only include projects whose
  // playback row actually points at a chapter.
  const continueRows = useMemo(() => {
    const rows: Array<{ project: Project; playback: PlaybackState }> = [];
    projects.forEach((p, idx) => {
      const pb = playbackQueries[idx]?.data;
      if (pb && pb.chapter_id) rows.push({ project: p, playback: pb });
    });
    rows.sort(
      (a, b) =>
        new Date(b.playback.updated_at).getTime() -
        new Date(a.playback.updated_at).getTime(),
    );
    return rows;
  }, [projects, playbackQueries]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl">Player</h1>
        <p className="text-muted text-sm mt-1">
          Resume where you left off, or pick a project to play.
        </p>
      </div>

      {projectsQ.isLoading && <p className="text-muted">Loading…</p>}
      {projectsQ.isError && (
        <p className="text-error">
          Failed to load projects: {(projectsQ.error as Error).message}
        </p>
      )}

      {continueRows.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xl font-display">Continue listening</h2>
          <ul className="flex gap-3 overflow-x-auto snap-x pb-2 md:grid md:grid-cols-2 md:gap-4 md:overflow-visible">
            {continueRows.map((row) => (
              <li
                key={row.project.id}
                className="shrink-0 snap-start w-72 md:w-auto"
              >
                <ContinueCard
                  project={row.project}
                  playback={row.playback}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-xl font-display">All projects</h2>
        {projects.length === 0 && !projectsQ.isLoading && (
          <div className="card p-8 text-center text-muted border-dashed">
            No projects yet. Create one from the Library tab.
          </div>
        )}
        {projects.length > 0 && (
          <ul className="grid gap-3">
            {projects.map((p) => (
              <li key={p.id}>
                <ProjectRow project={p} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ContinueCard({
  project,
  playback,
}: {
  project: Project;
  playback: PlaybackState;
}) {
  const chapterQ = useQuery({
    queryKey: ["chapter", playback.chapter_id],
    queryFn: () => api.getChapter(playback.chapter_id as string),
    enabled: !!playback.chapter_id,
    staleTime: 60_000,
  });

  const chTitle = chapterQ.data?.title
    ? chapterQ.data.title
    : chapterQ.data?.number != null
      ? `Chapter ${chapterQ.data.number}`
      : "Chapter";

  const handleResume = () => {
    if (!playback.chapter_id) return;
    // Fire-and-forget: loadChapter resolves when audio is ready. We don't
    // block navigation on it — Player route will show a loading state if
    // it arrives before the controller is ready.
    void playerController
      .loadChapter(project.id, playback.chapter_id)
      .then(() => playerController.play());
  };

  return (
    <div className="card p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-display text-lg leading-tight truncate">
            {project.title}
          </div>
          <div className="text-sm text-muted truncate">{chTitle}</div>
        </div>
      </div>
      <div className="text-xs text-muted">
        Last listened {timeAgo(playback.updated_at)}
      </div>
      <div className="flex gap-2 pt-1">
        <Link
          to={`/play/${project.id}?chapter=${playback.chapter_id}`}
          onClick={handleResume}
          className="btn-primary flex-1 text-center"
        >
          Resume
        </Link>
      </div>
    </div>
  );
}

function ProjectRow({ project }: { project: Project }) {
  return (
    <Link
      to={`/play/${project.id}`}
      className="card p-4 flex items-center justify-between gap-3
                 hover:border-accent/60 transition-colors"
    >
      <div className="min-w-0 flex-1">
        <div className="font-display text-lg leading-tight truncate">
          {project.title}
        </div>
        <div className="text-xs text-muted mt-0.5 flex items-center gap-2">
          <span className="chip uppercase tracking-wide text-[10px]">
            {project.status.replace(/_/g, " ")}
          </span>
          <span>
            {project.chapter_count > 0
              ? `${project.chapter_count} chapters`
              : "not yet ingested"}
          </span>
        </div>
      </div>
      <span
        className="btn-primary shrink-0"
        // The parent Link handles navigation; the span just styles like a CTA.
      >
        Play
      </span>
    </Link>
  );
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "recently";
  const deltaMs = Date.now() - then;
  if (deltaMs < 0) return "just now";
  const sec = Math.floor(deltaMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mo = Math.floor(day / 30);
  if (mo < 12) return `${mo}mo ago`;
  const yr = Math.floor(day / 365);
  return `${yr}y ago`;
}
