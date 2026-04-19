import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadViewMode());
  const [helpOpen, setHelpOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<ReviewFiltersState>(() =>
    loadFilters(chapterId),
  );

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

  const allSegments = segments.data ?? [];

  const visibleSegments = useMemo(
    () => applyFilters(allSegments, filters),
    [allSegments, filters],
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
  }, [segs, selectedId, helpOpen]);

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
              disabled
              title="Bulk actions coming in a later commit"
              className="btn-ghost min-h-tap text-xs opacity-60 cursor-not-allowed"
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
            />
          ) : (
            <TableView
              segments={segs}
              selectedId={selectedId}
              onSelect={setSelectedId}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
              onSelectAll={selectAll}
              onClearSelection={clearSelection}
            />
          )}
        </div>

        <aside className="hidden md:block">
          <div className="card p-4 text-sm text-muted sticky top-24">
            {selectedId ? (
              <>
                <div className="text-fg font-medium mb-1">Segment selected</div>
                <p>
                  The full detail panel (character reassignment, text edits,
                  emotion tags, preview) lands in a later commit.
                </p>
                <p className="mt-2 text-[11px] text-muted font-mono break-all">
                  id: {selectedId}
                </p>
              </>
            ) : (
              <p>Select a segment to view details.</p>
            )}
          </div>
        </aside>
      </div>

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
    </div>
  );
}
