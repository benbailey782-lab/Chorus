/**
 * Player route — `/play/:idOrSlug` full-screen audiobook player.
 *
 * Responsibilities:
 *   - Resolve initial chapter (?chapter= query → saved playback → first).
 *   - Kick off `playerController.loadChapter` once on mount.
 *   - Listen for `chorus:chapter-ended` and auto-advance when enabled.
 *   - Render the desktop three-column layout OR mobile single-column layout.
 *
 * The route intentionally DOES NOT call `playerController.close()` on
 * unmount — audio must keep playing when the user navigates elsewhere so the
 * (Commit 6) mini-player stays live.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import ChapterList from "../components/player/ChapterList";
import CoverArt from "../components/player/CoverArt";
import IncompleteChapterDialog from "../components/player/IncompleteChapterDialog";
import Scrubber from "../components/player/Scrubber";
import SpeedControl from "../components/player/SpeedControl";
import SyncedTextView from "../components/player/SyncedTextView";
import TransportControls from "../components/player/TransportControls";
import { api } from "../lib/api";
import { playerController } from "../lib/audioPlayer";
import { useToast } from "../lib/toast";
import { usePlayerStore } from "../stores/playerStore";

export default function Player() {
  const { idOrSlug = "" } = useParams();
  const [searchParams] = useSearchParams();
  const queryChapterId = searchParams.get("chapter");
  const { toast } = useToast();

  // ---- Data queries --------------------------------------------------------

  const projectQ = useQuery({
    queryKey: ["project", idOrSlug],
    queryFn: () => api.getProject(idOrSlug),
    enabled: !!idOrSlug,
  });

  const chaptersQ = useQuery({
    queryKey: ["chapters", idOrSlug],
    queryFn: () => api.listChapters(idOrSlug),
    enabled: !!idOrSlug,
  });

  const playbackQ = useQuery({
    queryKey: ["playback", idOrSlug],
    queryFn: () => api.getPlaybackState(idOrSlug),
    enabled: !!idOrSlug,
  });

  // ---- Responsive split ----------------------------------------------------

  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // ---- Store subscriptions (for rendering) --------------------------------

  const storeChapterId = usePlayerStore((s) => s.chapterId);
  const storeProjectIdOrSlug = usePlayerStore((s) => s.projectIdOrSlug);
  const segmentTimings = usePlayerStore((s) => s.segmentTimings);
  const currentSegmentId = usePlayerStore((s) => s.currentSegmentId);
  const missingSegments = usePlayerStore((s) => s.missingSegments);
  const assemblyError = usePlayerStore((s) => s.assemblyError);
  const autoAdvance = usePlayerStore((s) => s.autoAdvance);
  const setAutoAdvance = usePlayerStore((s) => s.setAutoAdvance);
  const assemblyProgress = usePlayerStore((s) => s.assemblyProgress);
  const status = usePlayerStore((s) => s.status);

  // ---- Initial chapter resolution + load ----------------------------------

  const chapters = useMemo(() => chaptersQ.data ?? [], [chaptersQ.data]);

  const initialChapterId = useMemo(() => {
    if (!chapters.length) return null;
    if (queryChapterId && chapters.some((c) => c.id === queryChapterId)) {
      return queryChapterId;
    }
    const saved = playbackQ.data?.chapter_id;
    if (saved && chapters.some((c) => c.id === saved)) return saved;
    return chapters[0].id;
  }, [chapters, queryChapterId, playbackQ.data]);

  // Load chapter exactly once per (project, chapterId) pair. The store is
  // cross-route; if the user already loaded this chapter elsewhere (e.g. the
  // mini-player), we leave the running session alone.
  useEffect(() => {
    if (!idOrSlug) return;
    if (!initialChapterId) return;
    // If the store already has THIS project + chapter loaded, don't reload —
    // the user may be mid-playback and we don't want to restart.
    if (
      storeProjectIdOrSlug === idOrSlug &&
      storeChapterId === initialChapterId
    ) {
      return;
    }
    void playerController.loadChapter(idOrSlug, initialChapterId);
    // Intentionally not `autoplay` — spec says don't auto-play on route mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idOrSlug, initialChapterId]);

  // ---- Chapter-ended handler ---------------------------------------------

  useEffect(() => {
    function handleChapterEnded(e: Event) {
      const ev = e as CustomEvent<{
        projectIdOrSlug: string | null;
        endedChapterId: string | null;
      }>;
      if (ev.detail.projectIdOrSlug !== idOrSlug) return;
      if (!usePlayerStore.getState().autoAdvance) return;
      if (!chapters.length) return;
      void playerController.next(chapters).then((advanced) => {
        if (!advanced) {
          toast({ kind: "success", message: "Book finished" });
        }
      });
    }
    window.addEventListener(
      "chorus:chapter-ended",
      handleChapterEnded as EventListener,
    );
    return () =>
      window.removeEventListener(
        "chorus:chapter-ended",
        handleChapterEnded as EventListener,
      );
  }, [idOrSlug, chapters, toast]);

  // ---- Keyboard shortcuts -------------------------------------------------

  useEffect(() => {
    function isEditable(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      return target.isContentEditable;
    }

    // Speed ladder shared with SpeedControl's desktop stepper.
    const LADDER = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    function stepSpeed(dir: -1 | 1) {
      const cur = usePlayerStore.getState().speed;
      let idx = LADDER.findIndex((v) => Math.abs(v - cur) < 1e-3);
      if (idx < 0) {
        idx = 0;
        let best = Infinity;
        LADDER.forEach((v, i) => {
          const d = Math.abs(v - cur);
          if (d < best) {
            best = d;
            idx = i;
          }
        });
      }
      const next = Math.max(0, Math.min(LADDER.length - 1, idx + dir));
      playerController.setSpeed(LADDER[next]);
    }

    function onKey(e: KeyboardEvent) {
      if (isEditable(e.target)) return;
      if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        const s = usePlayerStore.getState().status;
        if (s === "playing") playerController.pause();
        else playerController.play();
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        playerController.skip(-15);
        return;
      }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        playerController.skip(15);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        stepSpeed(+1);
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        stepSpeed(-1);
        return;
      }
      if (e.key === "PageUp") {
        e.preventDefault();
        void playerController.previous(chapters);
        return;
      }
      if (e.key === "PageDown") {
        e.preventDefault();
        void playerController.next(chapters);
        return;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chapters]);

  // ---- Derived view data -------------------------------------------------

  const currentChapter = useMemo(() => {
    if (!storeChapterId) return null;
    return chapters.find((c) => c.id === storeChapterId) ?? null;
  }, [chapters, storeChapterId]);

  const missingDialogOpen =
    !!storeChapterId && missingSegments.length > 0 && status === "error";

  // ---- Render branches ---------------------------------------------------

  if (projectQ.isLoading || chaptersQ.isLoading) {
    return <p className="text-muted">Loading player…</p>;
  }
  if (projectQ.isError) {
    return (
      <p className="text-error">
        {(projectQ.error as Error).message}{" "}
        <Link to="/" className="underline text-accent">
          Back to library
        </Link>
      </p>
    );
  }
  if (!projectQ.data) return null;

  const project = projectQ.data;

  if (chapters.length === 0) {
    return (
      <div className="card p-6 space-y-3">
        <h1 className="font-display text-2xl">{project.title}</h1>
        <p className="text-sm text-muted">
          This project has no chapters yet. Ingest a book first.
        </p>
        <Link to="/" className="btn-primary text-sm w-max">
          Back to library
        </Link>
      </div>
    );
  }

  // ------------------------------------------------------------------------
  // Desktop layout
  // ------------------------------------------------------------------------

  if (isDesktop) {
    return (
      <div className="h-[calc(100vh-9rem)] grid grid-cols-[280px_minmax(0,1fr)_minmax(0,1fr)] gap-4">
        <aside className="card overflow-hidden min-h-0">
          <ChapterList
            chapters={chapters}
            onSelect={(id) => {
              void playerController.loadChapter(idOrSlug, id).then(() => {
                playerController.play();
              });
            }}
          />
        </aside>

        <section className="flex flex-col min-h-0 max-w-2xl mx-auto w-full">
          <div className="space-y-4">
            <CoverArt
              title={project.title}
              chapterTitle={currentChapter?.title ?? undefined}
              chapterNumber={currentChapter?.number}
              ratio="wide"
            />
            <div className="text-center">
              <h1 className="font-display text-2xl leading-tight">
                {currentChapter?.title ??
                  (currentChapter ? `Chapter ${currentChapter.number}` : "—")}
              </h1>
              <p className="text-xs text-muted mt-1">{project.title}</p>
            </div>
            <AssemblyProgressBar
              status={status}
              progress={assemblyProgress}
              error={assemblyError}
            />
            <TransportControls chapters={chapters} />
            <Scrubber />
            <div className="flex items-center justify-between flex-wrap gap-3">
              <SpeedControl />
              <SettingsPopover
                autoAdvance={autoAdvance}
                onChange={setAutoAdvance}
              />
            </div>
          </div>
        </section>

        <aside className="card overflow-hidden min-h-0 flex flex-col">
          <div className="px-4 py-2 border-b border-border text-xs uppercase tracking-wider text-muted">
            Transcript
          </div>
          <div className="flex-1 min-h-0">
            <SyncedTextView
              timings={segmentTimings}
              currentSegmentId={currentSegmentId}
              onSeek={(ms) => playerController.seek(ms)}
            />
          </div>
        </aside>

        <IncompleteChapterDialog
          open={missingDialogOpen}
          missingCount={missingSegments.length}
          totalCount={segmentTimings.length || missingSegments.length}
          projectIdOrSlug={idOrSlug}
          chapterId={storeChapterId ?? ""}
          onClose={() => {
            // Clearing the error lets the dialog close without reloading.
            usePlayerStore.setState({
              missingSegments: [],
              assemblyError: null,
              status: "idle",
            });
          }}
        />
      </div>
    );
  }

  // ------------------------------------------------------------------------
  // Mobile layout
  // ------------------------------------------------------------------------

  return (
    <MobilePlayerLayout
      projectTitle={project.title}
      chapterNumber={currentChapter?.number}
      chapterTitle={currentChapter?.title ?? undefined}
      chapters={chapters}
      idOrSlug={idOrSlug}
      autoAdvance={autoAdvance}
      onToggleAutoAdvance={setAutoAdvance}
      status={status}
      assemblyProgress={assemblyProgress}
      assemblyError={assemblyError}
      missingDialog={
        <IncompleteChapterDialog
          open={missingDialogOpen}
          missingCount={missingSegments.length}
          totalCount={segmentTimings.length || missingSegments.length}
          projectIdOrSlug={idOrSlug}
          chapterId={storeChapterId ?? ""}
          onClose={() => {
            usePlayerStore.setState({
              missingSegments: [],
              assemblyError: null,
              status: "idle",
            });
          }}
        />
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Mobile sub-layout — split into its own component so the Player function
// stays readable.
// ---------------------------------------------------------------------------

import type { Chapter } from "../lib/api";
import type { PlayerStatus } from "../stores/playerStore";

function MobilePlayerLayout({
  projectTitle,
  chapterNumber,
  chapterTitle,
  chapters,
  idOrSlug,
  autoAdvance,
  onToggleAutoAdvance,
  status,
  assemblyProgress,
  assemblyError,
  missingDialog,
}: {
  projectTitle: string;
  chapterNumber: number | undefined;
  chapterTitle: string | undefined;
  chapters: Chapter[];
  idOrSlug: string;
  autoAdvance: boolean;
  onToggleAutoAdvance: (on: boolean) => void;
  status: PlayerStatus;
  assemblyProgress: number;
  assemblyError: string | null;
  missingDialog: React.ReactNode;
}) {
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const segmentTimings = usePlayerStore((s) => s.segmentTimings);
  const currentSegmentId = usePlayerStore((s) => s.currentSegmentId);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const preview = useMemo(() => {
    if (!segmentTimings.length) return [];
    const i = Math.max(0, currentSegmentIndex);
    return [
      segmentTimings[i - 1] ?? null,
      segmentTimings[i] ?? null,
      segmentTimings[i + 1] ?? null,
    ];
  }, [segmentTimings, currentSegmentIndex]);

  return (
    <div className="flex flex-col gap-4 pb-40">
      <header className="flex items-center gap-3">
        <Link
          to="/player"
          className="text-sm text-muted hover:text-fg shrink-0"
          aria-label="Back to player tab"
        >
          ←
        </Link>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-muted">
            {projectTitle}
          </div>
          <div className="text-sm truncate">
            {chapterNumber !== undefined && `Ch. ${chapterNumber}`}
            {chapterTitle && (
              <span className="text-muted"> · {chapterTitle}</span>
            )}
          </div>
        </div>
      </header>

      <CoverArt
        title={projectTitle}
        chapterTitle={chapterTitle}
        chapterNumber={chapterNumber}
        ratio="square"
      />

      <AssemblyProgressBar
        status={status}
        progress={assemblyProgress}
        error={assemblyError}
      />

      <button
        type="button"
        onClick={() => setTranscriptOpen(true)}
        aria-label="Expand transcript"
        className="card p-3 space-y-1 text-left hover:bg-surface-2 transition-colors"
      >
        {preview[0] ? (
          <p className="text-xs text-muted truncate">
            {preview[0].text_preview}
          </p>
        ) : (
          <p className="text-xs text-muted italic">—</p>
        )}
        {preview[1] ? (
          <p className="text-sm text-fg font-medium truncate">
            {preview[1].text_preview}
          </p>
        ) : (
          <p className="text-sm text-muted italic">
            {segmentTimings.length
              ? "Press play to start"
              : "No transcript available"}
          </p>
        )}
        {preview[2] ? (
          <p className="text-xs text-muted truncate">
            {preview[2].text_preview}
          </p>
        ) : (
          <p className="text-xs text-muted italic">—</p>
        )}
      </button>

      {/* Fixed bottom transport area — within thumb reach. */}
      <div
        className="fixed inset-x-0 bottom-[4.5rem] z-20 bg-bg/95 backdrop-blur
                   border-t border-border px-4 pt-3 pb-4 space-y-3"
        style={{
          paddingBottom: "calc(1rem + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <Scrubber />
        <div className="flex items-center justify-between gap-2">
          <SpeedControl compact />
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Player settings"
            className="chip min-h-tap text-xs"
          >
            ⚙︎
          </button>
        </div>
        <TransportControls chapters={chapters} compact />
      </div>

      {/* Transcript bottom sheet */}
      {transcriptOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Transcript"
          className="fixed inset-0 z-40 bg-bg/80 backdrop-blur flex items-end"
          onClick={() => setTranscriptOpen(false)}
        >
          <div
            className="bg-bg border-t border-border rounded-t-card h-[80vh] w-full flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-center py-2 shrink-0">
              <span
                aria-hidden="true"
                className="block h-1 w-10 rounded-full bg-border"
              />
            </div>
            <div className="flex items-center justify-between px-4 pb-2 shrink-0">
              <div className="text-xs uppercase tracking-wider text-muted">
                Transcript
              </div>
              <button
                type="button"
                onClick={() => setTranscriptOpen(false)}
                className="text-sm text-muted hover:text-fg"
              >
                Done
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <SyncedTextView
                timings={segmentTimings}
                currentSegmentId={currentSegmentId}
                onSeek={(ms) => playerController.seek(ms)}
              />
            </div>
          </div>
        </div>
      )}

      {/* Settings bottom sheet */}
      {settingsOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Player settings"
          className="fixed inset-0 z-40 bg-bg/80 backdrop-blur flex items-end"
          onClick={() => setSettingsOpen(false)}
        >
          <div
            className="bg-bg border-t border-border rounded-t-card w-full p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-center">
              <span
                aria-hidden="true"
                className="block h-1 w-10 rounded-full bg-border"
              />
            </div>
            <div className="font-display text-lg">Player settings</div>
            <AutoAdvanceToggle
              value={autoAdvance}
              onChange={onToggleAutoAdvance}
            />
            <div className="text-xs text-muted">
              Chapters from {projectTitle} · tap{" "}
              <Link to={`/project/${idOrSlug}/cast`} className="underline">
                cast
              </Link>{" "}
              to manage characters.
            </div>
            <button
              type="button"
              className="btn-surface w-full"
              onClick={() => setSettingsOpen(false)}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {missingDialog}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared small UI atoms
// ---------------------------------------------------------------------------

function AssemblyProgressBar({
  status,
  progress,
  error,
}: {
  status: PlayerStatus;
  progress: number;
  error: string | null;
}) {
  if (status !== "loading") return null;
  const pct = Math.max(5, Math.min(100, progress));
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex justify-between text-[10px] uppercase tracking-wider text-muted">
        <span>Assembling</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div
          className="h-full bg-accent transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}

function SettingsPopover({
  autoAdvance,
  onChange,
}: {
  autoAdvance: boolean;
  onChange: (on: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Player settings"
        className="chip min-h-tap text-xs"
      >
        ⚙︎ Settings
      </button>
      {open && (
        <div
          className="absolute right-0 bottom-full mb-2 w-64 card p-3 space-y-3 shadow-xl z-20"
          onMouseLeave={() => setOpen(false)}
        >
          <AutoAdvanceToggle value={autoAdvance} onChange={onChange} />
        </div>
      )}
    </div>
  );
}

function AutoAdvanceToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer min-h-tap">
      <span className="text-sm">
        <span className="block">Auto-advance</span>
        <span className="block text-xs text-muted">
          Play next chapter automatically.
        </span>
      </span>
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-5 w-5 accent-accent"
      />
    </label>
  );
}
