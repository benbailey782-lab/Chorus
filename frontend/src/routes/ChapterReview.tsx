import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import BulkActionsMenu from "../components/review/BulkActionsMenu";
import DetailPanel from "../components/review/DetailPanel";
import GenerateModal from "../components/review/GenerateModal";
import GenerationProgressBar from "../components/review/GenerationProgressBar";
import KeyboardHelp from "../components/review/KeyboardHelp";
import ProseView from "../components/review/ProseView";
import ReviewFilters from "../components/review/ReviewFilters";
import StatusBar from "../components/review/StatusBar";
import TableView from "../components/review/TableView";
import { api, type Character, type Job, type SegmentCharacter } from "../lib/api";
import {
  EMPTY_FILTERS,
  applyFilters,
  countActiveFilters,
  loadFilters,
  loadViewMode,
  saveFilters,
  saveViewMode,
  type ReviewFiltersState,
  type ViewMode,
} from "../lib/review-filters";

const ACTIVE_STATUSES = new Set<Job["status"]>([
  "queued",
  "running",
  "awaiting_response",
]);

export default function ChapterReview() {
  const { idOrSlug = "", chapterId = "" } = useParams();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadViewMode());
  const [helpOpen, setHelpOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<ReviewFiltersState>(() =>
    loadFilters(chapterId),
  );
  const [generateModalOpen, setGenerateModalOpen] = useState(false);
  // When a user clicks a segment's play icon in the list views we want the
  // DetailPanel to autoplay on next mount/select. Cleared by DetailPanel once
  // consumed.
  const [playOnSelect, setPlayOnSelect] = useState(false);
  // Mobile bottom-sheet detection. `null` until mount so SSR/first paint
  // matches whatever the responsive layout had — we only treat it as mobile
  // once matchMedia confirms.
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // When the route-level chapterId changes (e.g., user navigates between
  // chapters without a full remount) re-load the stored filter set for that
  // chapter so each chapter keeps its own filter memory.
  useEffect(() => {
    setFilters(loadFilters(chapterId));
    setSelectedIds(new Set());
  }, [chapterId]);

  useEffect(() => {
    saveViewMode(viewMode);
  }, [viewMode]);

  useEffect(() => {
    saveFilters(chapterId, filters);
  }, [chapterId, filters]);

  const chapter = useQuery({
    queryKey: ["chapter", chapterId],
    queryFn: () => api.getChapter(chapterId),
    enabled: !!chapterId,
  });

  // Polls project jobs so the segment list can refetch while an
  // attribute_chapter job is in flight (matches Casting.tsx / PendingJobsBanner
  // cadence).
  const jobs = useQuery({
    queryKey: ["project-jobs", idOrSlug],
    queryFn: () => api.listProjectJobs(idOrSlug),
    enabled: !!idOrSlug,
    refetchInterval: (q) => {
      const data = q.state.data as Job[] | undefined;
      if (!data) return 2000;
      return data.some((j) => ACTIVE_STATUSES.has(j.status)) ? 2000 : false;
    },
  });

  const chapterHasActiveJob = useMemo(() => {
    const list = jobs.data ?? [];
    return list.some(
      (j) =>
        j.kind === "attribute_chapter" &&
        ACTIVE_STATUSES.has(j.status) &&
        // job.payload may carry chapter_id — be permissive because older jobs
        // pre-date the field.
        (j.payload as { chapter_id?: string } | null)?.chapter_id === chapterId,
    );
  }, [jobs.data, chapterId]);

  const segments = useQuery({
    queryKey: ["segments", chapterId],
    queryFn: () => api.listSegments(chapterId),
    enabled: !!chapterId,
    refetchInterval: chapterHasActiveJob ? 2000 : false,
  });

  // Characters: Casting.tsx uses ["characters", idOrSlug] and
  // api.listCharacters — keep them the same cache-key so both routes share
  // data.
  const charactersQuery = useQuery({
    queryKey: ["characters", idOrSlug],
    queryFn: () => api.listCharacters(idOrSlug),
    enabled: !!idOrSlug,
  });

  // Phase-5 generation queries. Voicebox health is global; estimate is
  // per-chapter + short-lived; status is polled while anything is in flight.
  const { data: voiceboxHealth } = useQuery({
    queryKey: ["voicebox-health"],
    queryFn: api.voiceboxHealth,
    staleTime: 30_000,
  });

  const { data: genEstimate } = useQuery({
    queryKey: ["gen-estimate", chapterId],
    queryFn: () => api.chapterGenerationEstimate(chapterId),
    enabled: !!chapterId,
    staleTime: 10_000,
  });

  const { data: genStatus } = useQuery({
    queryKey: ["gen-status", chapterId],
    queryFn: () => api.chapterGenerationStatus(chapterId),
    enabled: !!chapterId,
    refetchInterval: (q) => {
      const d = q.state.data as
        | { in_progress_job_ids?: string[] }
        | undefined;
      return d?.in_progress_job_ids && d.in_progress_job_ids.length > 0
        ? 2000
        : false;
    },
  });

  const allSegments = segments.data ?? [];

  const visibleSegments = useMemo(
    () => applyFilters(allSegments, filters),
    [allSegments, filters],
  );

  const selectedSegment = useMemo(
    () => allSegments.find((s) => s.id === selectedId) ?? null,
    [allSegments, selectedId],
  );

  // The ReviewFilters speaker list expects SegmentCharacter-shaped rows. The
  // full Character object from Casting has extra fields we don't need here;
  // narrow to the subset the filter UI uses so we can drop the extras cheaply.
  const filterCharacters = useMemo<SegmentCharacter[]>(() => {
    const rows = (charactersQuery.data ?? []) as Character[];
    return rows.map((c) => ({
      id: c.id,
      name: c.name,
      character_archetype: c.character_archetype,
      voice_id: c.voice_id,
    }));
  }, [charactersQuery.data]);

  // Default-select the first *visible* segment when data lands so keyboard
  // nav follows the filtered set. If the currently selected id is filtered
  // out, reset to the first visible.
  useEffect(() => {
    if (visibleSegments.length === 0) return;
    if (!selectedId || !visibleSegments.some((s) => s.id === selectedId)) {
      setSelectedId(visibleSegments[0].id);
    }
  }, [visibleSegments, selectedId]);

  // Reference kept for keyboard-nav convenience; j/k walk the currently
  // visible (filtered) set.
  const segs = visibleSegments;

  const activeFilterCount = countActiveFilters(filters);

  // Multi-select helpers (TableView → row checkboxes + select-all). The full
  // BulkActionsMenu lands in P8; here we just own the Set<string> so it's
  // ready to plug in.
  function toggleSelect(id: string) {
    setSelectedIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function selectAll(ids: string[]) {
    setSelectedIds(new Set(ids));
  }
  function clearSelection() {
    setSelectedIds(new Set());
  }

  // Keyboard shortcuts — suppressed when focus is in an editable element so
  // typing doesn't accidentally navigate.
  useEffect(() => {
    function isEditable(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      return target.isContentEditable;
    }

    function onKey(e: KeyboardEvent) {
      if (isEditable(e.target)) return;
      // Cmd/Ctrl+A selects all visible rows — only meaningful in table view.
      // We intercept before the browser's native select-all takes over, but
      // only when the table view is active. Other views pass through.
      if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
        if (viewMode !== "table") return;
        if (segs.length === 0) return;
        e.preventDefault();
        setSelectedIds(new Set(segs.map((s) => s.id)));
        return;
      }
      // ? toggles help regardless of other state. Shift+/ on US keyboards
      // reports as "?"; accept both forms.
      if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
        e.preventDefault();
        setHelpOpen((v) => !v);
        return;
      }
      if (e.key === "Escape") {
        if (helpOpen) {
          setHelpOpen(false);
          return;
        }
        setSelectedId(null);
        return;
      }
      if (
        e.key === "ArrowDown" ||
        e.key === "j" ||
        e.key === "ArrowUp" ||
        e.key === "k"
      ) {
        if (segs.length === 0) return;
        e.preventDefault();
        const idx = Math.max(
          0,
          segs.findIndex((s) => s.id === selectedId),
        );
        const dir = e.key === "ArrowDown" || e.key === "j" ? 1 : -1;
        const next = Math.max(0, Math.min(segs.length - 1, idx + dir));
        setSelectedId(segs[next].id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [segs, selectedId, helpOpen, viewMode]);

  if (chapter.isLoading) return <p className="text-muted">Loading chapter…</p>;
  if (chapter.isError) {
    return (
      <p className="text-error">
        {(chapter.error as Error).message}{" "}
        <Link to={`/project/${idOrSlug}/cast`} className="underline text-accent">
          Back
        </Link>
      </p>
    );
  }
  if (!chapter.data) return null;

  const ch = chapter.data;

  return (
    <div className="flex flex-col min-h-[calc(100vh-8rem)]">
      {/* Sticky toolbar -------------------------------------------------- */}
      <div className="sticky top-[3.25rem] z-10 -mx-4 px-4 py-2 border-b
                      border-border bg-bg/90 backdrop-blur">
        <div className="flex items-center gap-3 flex-wrap">
          <Link
            to={`/project/${idOrSlug}/cast`}
            className="text-sm text-muted hover:text-fg shrink-0"
          >
            ← {ch.title || `Chapter ${ch.number}`}
          </Link>

          <span className="chip text-[10px] uppercase tracking-wider text-muted">
            {(ch.word_count ?? 0).toLocaleString()} words · {allSegments.length} segs
            {visibleSegments.length !== allSegments.length && (
              <> · {visibleSegments.length} shown</>
            )}
          </span>

          {ch.pov_character_name && (
            <span className="chip text-[10px] uppercase tracking-wider text-accent">
              POV: {ch.pov_character_name}
            </span>
          )}

          <div className="ml-auto flex items-center gap-2 flex-wrap">
            <div
              role="tablist"
              aria-label="View mode"
              className="inline-flex rounded-card border border-border overflow-hidden"
            >
              <button
                type="button"
                role="tab"
                aria-selected={viewMode === "prose"}
                onClick={() => setViewMode("prose")}
                className={`min-h-tap px-3 text-xs uppercase tracking-wider
                            ${
                              viewMode === "prose"
                                ? "bg-accent text-accent-fg"
                                : "text-muted hover:text-fg"
                            }`}
              >
                Prose
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={viewMode === "table"}
                onClick={() => setViewMode("table")}
                className={`min-h-tap px-3 text-xs uppercase tracking-wider
                            border-l border-border
                            ${
                              viewMode === "table"
                                ? "bg-accent text-accent-fg"
                                : "text-muted hover:text-fg"
                            }`}
              >
                Table
              </button>
            </div>

            {(() => {
              const ungenerated = genEstimate?.segments ?? 0;
              const voiceboxReachable = !!(
                voiceboxHealth?.enabled && voiceboxHealth.reachable
              );
              const canGenerate = ungenerated > 0;
              const styleClass =
                canGenerate && voiceboxReachable ? "btn-primary" : "btn-surface";
              return (
                <button
                  type="button"
                  disabled={!canGenerate}
                  onClick={() => setGenerateModalOpen(true)}
                  title={
                    !canGenerate
                      ? "All segments already have audio"
                      : voiceboxReachable
                        ? "Generate audio for ungenerated segments"
                        : "Generate (Voicebox offline)"
                  }
                  className={`${styleClass} min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  Generate ({ungenerated})
                </button>
              );
            })()}

            <Link
              to={`/play/${idOrSlug}?chapter=${chapterId}`}
              className="btn-surface min-h-tap text-xs"
              title="Open this chapter in the full-screen player"
            >
              Play chapter
            </Link>

            <button
              type="button"
              onClick={() => setFiltersOpen(true)}
              title="Filters"
              className="btn-ghost min-h-tap text-xs relative"
            >
              Filters
              {activeFilterCount > 0 && (
                <span
                  aria-hidden="true"
                  className="absolute -top-1 -right-1 bg-accent text-black
                             text-[10px] font-bold rounded-full h-5 w-5
                             grid place-items-center"
                >
                  {activeFilterCount}
                </span>
              )}
            </button>

            <button
              type="button"
              disabled={selectedIds.size === 0}
              onClick={() => {
                // Switch to table view (bulk actions are table-view centric);
                // the BulkActionsMenu is already mounted below whenever the
                // selection is non-empty, so clicking here just ensures the
                // selection bar / FAB is visible on the right surface.
                if (viewMode !== "table") setViewMode("table");
              }}
              title={
                selectedIds.size === 0
                  ? "Select segments to enable bulk actions"
                  : "Bulk actions"
              }
              className={`btn-ghost min-h-tap text-xs ${
                selectedIds.size === 0
                  ? "opacity-60 cursor-not-allowed"
                  : "text-accent"
              }`}
            >
              Bulk {selectedIds.size > 0 && <>({selectedIds.size})</>}
            </button>

            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              title="Keyboard shortcuts (?)"
              className="btn-ghost min-h-tap min-w-tap text-xs"
              aria-label="Show keyboard shortcuts"
            >
              ?
            </button>
          </div>
        </div>
        {genStatus &&
          genStatus.in_progress_job_ids &&
          genStatus.in_progress_job_ids.length > 0 && (
            <GenerationProgressBar status={genStatus} estimate={genEstimate} />
          )}
      </div>

      {/* Main area ------------------------------------------------------- */}
      <div className="flex-1 grid gap-4 mt-4 md:grid-cols-[3fr_2fr]">
        <div className="min-w-0">
          {segments.isLoading ? (
            <p className="text-muted text-sm">Loading segments…</p>
          ) : segments.isError ? (
            <p className="text-error text-sm">
              {(segments.error as Error).message}
            </p>
          ) : viewMode === "prose" ? (
            <ProseView
              segments={segs}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onPlay={(id) => {
                setSelectedId(id);
                setPlayOnSelect(true);
              }}
            />
          ) : (
            <>
              <BulkActionsMenu
                selectedIds={selectedIds}
                segments={visibleSegments}
                characters={filterCharacters}
                onDone={clearSelection}
              />
              <TableView
                segments={segs}
                selectedId={selectedId}
                onSelect={setSelectedId}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onSelectAll={selectAll}
                onClearSelection={clearSelection}
                onPlay={(id) => {
                  setSelectedId(id);
                  setPlayOnSelect(true);
                }}
              />
            </>
          )}
        </div>

        <aside className="hidden md:block">
          <div className="card p-0 sticky top-24 max-h-[calc(100vh-8rem)] overflow-hidden flex flex-col">
            <DetailPanel
              segment={selectedSegment}
              characters={filterCharacters}
              voiceboxHealth={voiceboxHealth}
              autoPlay={playOnSelect}
              onAutoPlayConsumed={() => setPlayOnSelect(false)}
              chapterId={chapterId}
              onSaved={() =>
                queryClient.invalidateQueries({
                  queryKey: ["segments", chapterId],
                })
              }
            />
          </div>
        </aside>
      </div>

      {/* Mobile bottom sheet ------------------------------------------- */}
      {isMobile && (
        <div
          aria-hidden={selectedSegment ? undefined : true}
          className={`fixed inset-x-0 bottom-0 z-30 md:hidden transition-transform duration-200
                      ${selectedSegment ? "translate-y-0" : "translate-y-full pointer-events-none"}`}
          style={{ height: "70vh" }}
        >
          <div className="h-full bg-bg border-t border-border rounded-t-card shadow-xl flex flex-col">
            <div className="flex justify-center py-2 shrink-0">
              <span
                aria-hidden="true"
                className="block h-1 w-10 rounded-full bg-border"
              />
            </div>
            <div className="flex-1 min-h-0">
              <DetailPanel
                segment={selectedSegment}
                characters={filterCharacters}
                voiceboxHealth={voiceboxHealth}
                autoPlay={playOnSelect}
                onAutoPlayConsumed={() => setPlayOnSelect(false)}
                chapterId={chapterId}
                onClose={() => setSelectedId(null)}
                onSaved={() =>
                  queryClient.invalidateQueries({
                    queryKey: ["segments", chapterId],
                  })
                }
              />
            </div>
          </div>
        </div>
      )}

      <StatusBar segments={visibleSegments} />

      <ReviewFilters
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        filters={filters}
        onChange={setFilters}
        onClear={() => setFilters(EMPTY_FILTERS)}
        characters={filterCharacters}
      />

      <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)} />

      <GenerateModal
        open={generateModalOpen}
        onClose={() => setGenerateModalOpen(false)}
        chapterId={chapterId}
        estimate={genEstimate}
        voiceboxHealth={voiceboxHealth}
      />
    </div>
  );
}
