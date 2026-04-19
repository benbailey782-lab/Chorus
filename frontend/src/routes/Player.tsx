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

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import ChapterList from "../components/player/ChapterList";
import CoverArt from "../components/player/CoverArt";
import IncompleteChapterDialog from "../components/player/IncompleteChapterDialog";
import MobileControlsSheet from "../components/player/MobileControlsSheet";
import MobilePlayerCard from "../components/player/MobilePlayerCard";
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
  const segmentTimingsLoading = usePlayerStore((s) => s.segmentTimingsLoading);
  const currentSegmentId = usePlayerStore((s) => s.currentSegmentId);
  const missingSegments = usePlayerStore((s) => s.missingSegments);
  const assemblyError = usePlayerStore((s) => s.assemblyError);
  const autoAdvance = usePlayerStore((s) => s.autoAdvance);
  const setAutoAdvance = usePlayerStore((s) => s.setAutoAdvance);
  const assemblyProgress = usePlayerStore((s) => s.assemblyProgress);
  const status = usePlayerStore((s) => s.status);
  const restoredPositionMs = usePlayerStore((s) => s.restoredPositionMs);

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
          // End-of-book. Flip to a definitive 'finished' state so the UI
          // stops spinning on "loading" and surfaces a Replay CTA.
          usePlayerStore.setState({ status: "finished" });
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
            <ResumeHint restoredPositionMs={restoredPositionMs} status={status} />
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
              loading={segmentTimingsLoading}
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
      currentChapterId={storeChapterId}
      autoAdvance={autoAdvance}
      onToggleAutoAdvance={setAutoAdvance}
      status={status}
      assemblyProgress={assemblyProgress}
      assemblyError={assemblyError}
      restoredPositionMs={restoredPositionMs}
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

/**
 * MobilePlayerLayout — Phase 6.6 commit 3.
 *
 * Target viewport: 375×812 (iPhone). Fits exactly:
 *   - 44px compressed header (back / title / overflow)
 *   - 520px flip card (cover ↔ transcript)
 *   - ~100px transport row (scrubber + 5-button cluster)
 *   - ~60px swipe-up indicator + breathing room
 *   - 88px BottomNav (fixed, outside this flex tree)
 *
 * The outer `<div>` pins itself to the viewport height minus the BottomNav
 * so the transport row ends FLUSH above the nav, no dead gap. The BottomNav
 * is `fixed bottom-0` inside Layout.tsx; we reserve its ~88px space via
 * `calc(100dvh - 88px - safe-area-inset-bottom)`.
 *
 * The "View full transcript" link from Phase 6.5 is dropped here to make
 * the 812px math work; users still reach the transcript by flipping the
 * card (tap to flip, per Phase 6.5 commit 4).
 *
 * Settings cog is also dropped — auto-advance moves into the swipe-up
 * MobileControlsSheet, accessible via the overflow-menu button in the
 * header OR the swipe-up indicator pill below the transport controls.
 */
function MobilePlayerLayout({
  projectTitle,
  chapterNumber,
  chapterTitle,
  chapters,
  idOrSlug,
  currentChapterId,
  autoAdvance,
  onToggleAutoAdvance,
  status,
  assemblyProgress,
  assemblyError,
  restoredPositionMs,
  missingDialog,
}: {
  projectTitle: string;
  chapterNumber: number | undefined;
  chapterTitle: string | undefined;
  chapters: Chapter[];
  idOrSlug: string;
  currentChapterId: string | null;
  autoAdvance: boolean;
  onToggleAutoAdvance: (on: boolean) => void;
  status: PlayerStatus;
  assemblyProgress: number;
  assemblyError: string | null;
  restoredPositionMs: number | null;
  missingDialog: React.ReactNode;
}) {
  const [controlsOpen, setControlsOpen] = useState(false);

  const segmentTimings = usePlayerStore((s) => s.segmentTimings);
  const segmentTimingsLoading = usePlayerStore((s) => s.segmentTimingsLoading);
  const currentSegmentId = usePlayerStore((s) => s.currentSegmentId);
  const storeChapterId = usePlayerStore((s) => s.chapterId);

  // Build a lightweight chapter shape for the flip card header. Using the
  // store's chapterId (not just number/title) keeps the card honest when the
  // user advances chapters mid-session.
  const cardChapter = useMemo(() => {
    if (chapterNumber === undefined) return null;
    return {
      id: storeChapterId ?? "",
      number: chapterNumber,
      title: chapterTitle ?? null,
    };
  }, [storeChapterId, chapterNumber, chapterTitle]);

  // Swipe-up gesture on the indicator pill → open the controls sheet. Very
  // small threshold (30px) so the gesture feels responsive. Tap also works
  // via the button onClick handler.
  const indicatorDragStart = useRef<number | null>(null);
  function onIndicatorPointerDown(e: React.PointerEvent) {
    indicatorDragStart.current = e.clientY;
  }
  function onIndicatorPointerMove(e: React.PointerEvent) {
    if (indicatorDragStart.current === null) return;
    const dy = e.clientY - indicatorDragStart.current;
    if (dy < -30) {
      indicatorDragStart.current = null;
      setControlsOpen(true);
    }
  }
  function onIndicatorPointerEnd() {
    indicatorDragStart.current = null;
  }

  // Chapter title shown in the center of the 44px header. Prefer the full
  // chapter title; fall back to "Ch. N" when unavailable.
  const headerTitle =
    chapterTitle ??
    (chapterNumber !== undefined ? `Chapter ${chapterNumber}` : projectTitle);

  return (
    <div
      className="flex flex-col"
      style={{
        // 100dvh accounts for mobile browser chrome better than 100vh.
        // Subtract the BottomNav (~4rem visual + safe-area-inset-bottom)
        // so the player's last row sits flush against the nav.
        height:
          "calc(100dvh - 4rem - env(safe-area-inset-bottom, 0px))",
      }}
    >
      {/* 44px compressed header — back / chapter title / overflow. */}
      <header
        className="h-11 shrink-0 flex items-center gap-2 px-3 border-b border-border"
        style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
      >
        <Link
          to="/player"
          className="h-8 w-8 shrink-0 grid place-items-center rounded-full
                     text-muted hover:text-fg hover:bg-surface-2"
          aria-label="Back to player tab"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </Link>
        <div className="min-w-0 flex-1 text-center">
          <div className="text-base font-medium truncate">{headerTitle}</div>
        </div>
        <button
          type="button"
          onClick={() => setControlsOpen(true)}
          aria-label="More player controls"
          className="h-8 w-8 shrink-0 grid place-items-center rounded-full
                     text-muted hover:text-fg hover:bg-surface-2"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="currentColor"
            aria-hidden="true"
          >
            <circle cx="5" cy="12" r="1.7" />
            <circle cx="12" cy="12" r="1.7" />
            <circle cx="19" cy="12" r="1.7" />
          </svg>
        </button>
      </header>

      {/* Flip card fills available space between header and transport row.
          Phase6.7-fix: prior layout had `max-h-[520px]` which left a dead
          strip on iPhone 15 Pro Max (932px viewport) — the card clamped at
          520px while the column had room to breathe. We now let the outer
          flex-1 grow to ALL available height, and center-content a square
          card inside. The card picks the smaller of its width-based or
          height-based constraint (aspect-square + max-h-full) so:
            - iPhone SE 375×667: card shrinks to fit the cramped column
            - iPhone 14 375×812: card ~360-400px square
            - iPhone 15 Pro Max 430×932: card grows to ~500-560px square
          Desktop layout (min-width:1024px) is unaffected — it's a
          different branch above. */}
      {/*
        Flip card container — phase6.7-fix.

        Before: outer div had `h-full max-h-[520px]` which clamped the
        card at 520px, leaving a dead strip above the transport row on
        tall viewports (iPhone 15 Pro Max at 932px had ~60-80px of
        wasted space). Also `overflow-hidden` + height-unbounded child
        caused the card to draw outside the container on shorter
        viewports.

        After: the container is a centered flex box with
        `containerType: size` so the inner square can size via
        container-query units `cqmin` — which picks the SMALLER of the
        container's width or height. That's exactly the "largest square
        that fits" constraint. Result:
          - iPhone SE 375×667 (column ~320px tall, ~343px wide after
            padding): card = 320px square (height-bound).
          - iPhone 14 375×812 (column ~440px tall, 343px wide): card
            = 343px square (width-bound).
          - iPhone 15 Pro Max 430×932 (column ~580px tall, 398px wide):
            card = 398px square (width-bound, no dead space above/below
            — the flex `items-center` centers the card vertically).

        MobilePlayerCard already sets `aspect-square` on its inner flip
        container, so we only need to size the wrapper correctly.
      */}
      <div
        className="flex-1 min-h-0 flex items-center justify-center px-4 pt-3 pb-2"
        style={{ containerType: "size" }}
      >
        <div
          className="aspect-square"
          style={{
            width: "min(100cqw, 100cqh)",
            maxWidth: "100%",
            maxHeight: "100%",
          }}
        >
          <MobilePlayerCard
            chapter={cardChapter}
            segmentTimings={segmentTimings}
            currentSegmentId={currentSegmentId}
            onSegmentSeek={(ms) => playerController.seek(ms)}
            projectTitle={projectTitle}
            segmentTimingsLoading={segmentTimingsLoading}
          />
        </div>
      </div>

      {/* Assembly progress sits above the transport row when active. */}
      <div className="px-4">
        <AssemblyProgressBar
          status={status}
          progress={assemblyProgress}
          error={assemblyError}
        />
      </div>

      {/* Transport row: scrubber + 5-button cluster with inline speed pill.
          Flush above the swipe-up indicator; no fixed positioning. */}
      <div className="shrink-0 px-4 pt-1 pb-1 space-y-2">
        <ResumeHint restoredPositionMs={restoredPositionMs} status={status} />
        <Scrubber />
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <TransportControls chapters={chapters} compact />
          </div>
          <SpeedControl compact />
        </div>
      </div>

      {/* Swipe-up indicator — tappable pill + swipe-up gesture opens the
          MobileControlsSheet. ~40px wide, 3px tall, opacity-30. */}
      <div className="shrink-0 pt-3 pb-4 flex justify-center">
        <button
          type="button"
          onClick={() => setControlsOpen(true)}
          onPointerDown={onIndicatorPointerDown}
          onPointerMove={onIndicatorPointerMove}
          onPointerUp={onIndicatorPointerEnd}
          onPointerCancel={onIndicatorPointerEnd}
          aria-label="Open player controls"
          className="h-[3px] w-10 rounded-full bg-fg opacity-30
                     hover:opacity-60 transition-opacity touch-none"
        />
      </div>

      <MobileControlsSheet
        open={controlsOpen}
        onClose={() => setControlsOpen(false)}
        autoAdvance={autoAdvance}
        onToggleAutoAdvance={onToggleAutoAdvance}
        chapters={chapters}
        currentChapterId={currentChapterId}
        projectIdOrSlug={idOrSlug}
      />

      {missingDialog}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared small UI atoms
// ---------------------------------------------------------------------------

/**
 * Soft-restore hint shown after a refresh when the controller reseated
 * the scrubber at the last-saved position. Clicking play clears
 * `restoredPositionMs` in the store, which hides this chip.
 */
function ResumeHint({
  restoredPositionMs,
  status,
}: {
  restoredPositionMs: number | null;
  status: PlayerStatus;
}) {
  if (restoredPositionMs === null || restoredPositionMs <= 0) return null;
  if (status !== "paused" && status !== "ready") return null;
  const totalSec = Math.floor(restoredPositionMs / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  const label = m > 0 ? `${m}m ${s}s` : `${s}s`;
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center"
    >
      <span className="chip text-[11px] text-muted">
        Resumed at {label} — press play to continue
      </span>
    </div>
  );
}

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
