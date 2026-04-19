import { useEffect } from "react";

import { RENDER_MODES } from "../../lib/constants";
import type { RenderMode, SegmentCharacter } from "../../lib/api";
import {
  EMPTY_FILTERS,
  UNATTRIBUTED_ID,
  type ReviewFiltersState,
} from "../../lib/review-filters";

// Re-export so routes can import from a single place.
export { EMPTY_FILTERS, isFilterActive } from "../../lib/review-filters";
export type { ReviewFiltersState } from "../../lib/review-filters";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: ReviewFiltersState;
  onChange: (next: ReviewFiltersState) => void;
  onClear: () => void;
  characters: SegmentCharacter[];
}

function toggleInSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export default function ReviewFilters({
  open,
  onClose,
  filters,
  onChange,
  onClear,
  characters,
}: Props) {
  // ESC closes the drawer — matches common modal UX.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const sortedCharacters = [...characters].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  function patch(next: Partial<ReviewFiltersState>) {
    onChange({ ...filters, ...next });
  }

  function toggleSpeaker(id: string) {
    patch({ speakers: toggleInSet(filters.speakers, id) });
  }

  function toggleMode(mode: RenderMode) {
    patch({ renderModes: toggleInSet(filters.renderModes, mode) });
  }

  // Dual-range: when the user drags the "min" handle past "max" (or vice
  // versa), clamp so the values don't crisscross.
  function setConfMin(raw: number) {
    const v = Math.max(0, Math.min(100, Math.round(raw)));
    patch({
      confidenceMin: Math.min(v, filters.confidenceMax),
    });
  }
  function setConfMax(raw: number) {
    const v = Math.max(0, Math.min(100, Math.round(raw)));
    patch({
      confidenceMax: Math.max(v, filters.confidenceMin),
    });
  }

  return (
    <>
      {/* Backdrop --------------------------------------------------------- */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={`fixed inset-0 z-30 bg-black/40 backdrop-blur-sm transition-opacity
                    ${open ? "opacity-100" : "opacity-0 pointer-events-none"}`}
      />

      {/* Panel: desktop drawer / mobile bottom sheet ---------------------- */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Review filters"
        className={`fixed z-40 bg-surface border-border text-sm flex flex-col
                    transition-transform
                    /* Mobile: bottom sheet */
                    left-0 right-0 bottom-0 rounded-t-card border-t
                    h-[70vh] max-h-[90vh]
                    ${open ? "translate-y-0" : "translate-y-full"}
                    /* Desktop: right-side drawer (overrides mobile classes
                       via sm:/lg: breakpoints) */
                    sm:left-auto sm:right-0 sm:top-0 sm:bottom-0 sm:h-full
                    sm:w-[360px] sm:max-h-none sm:rounded-none sm:border-t-0
                    sm:border-l
                    ${
                      open
                        ? "sm:translate-y-0 sm:translate-x-0"
                        : "sm:translate-y-0 sm:translate-x-full"
                    }`}
      >
        {/* Header ------------------------------------------------------- */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border shrink-0">
          <h2 className="font-display text-lg text-fg flex-1">Filters</h2>
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-muted hover:text-fg uppercase tracking-wider"
          >
            Clear all
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close filters"
            className="min-h-tap min-w-tap text-muted hover:text-fg text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Body ---------------------------------------------------------- */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
          {/* Speakers --------------------------------------------------- */}
          <section>
            <h3 className="text-[11px] uppercase tracking-wider text-muted mb-2">
              Speakers
            </h3>
            <div className="space-y-1 max-h-60 overflow-y-auto pr-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer hover:text-fg">
                <input
                  type="checkbox"
                  checked={filters.speakers.has(UNATTRIBUTED_ID)}
                  onChange={() => toggleSpeaker(UNATTRIBUTED_ID)}
                  className="h-4 w-4 accent-accent"
                />
                <span className="italic text-muted">Unattributed</span>
              </label>
              {sortedCharacters.length === 0 && (
                <p className="text-xs text-muted italic">
                  No characters cast yet.
                </p>
              )}
              {sortedCharacters.map((c) => (
                <label
                  key={c.id}
                  className="flex items-center gap-2 text-sm cursor-pointer hover:text-fg"
                >
                  <input
                    type="checkbox"
                    checked={filters.speakers.has(c.id)}
                    onChange={() => toggleSpeaker(c.id)}
                    className="h-4 w-4 accent-accent"
                  />
                  <span>{c.name}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Confidence range ------------------------------------------- */}
          <section>
            <h3 className="text-[11px] uppercase tracking-wider text-muted mb-2">
              Confidence
            </h3>
            <div className="flex items-center justify-between text-xs font-mono mb-2">
              <span>{filters.confidenceMin}</span>
              <span className="text-muted">to</span>
              <span>{filters.confidenceMax}</span>
            </div>
            <div className="space-y-2">
              <label className="block text-[10px] uppercase tracking-wider text-muted">
                Min
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={filters.confidenceMin}
                  onChange={(e) => setConfMin(Number(e.target.value))}
                  className="w-full accent-accent"
                />
              </label>
              <label className="block text-[10px] uppercase tracking-wider text-muted">
                Max
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={filters.confidenceMax}
                  onChange={(e) => setConfMax(Number(e.target.value))}
                  className="w-full accent-accent"
                />
              </label>
            </div>
          </section>

          {/* Render modes ----------------------------------------------- */}
          <section>
            <h3 className="text-[11px] uppercase tracking-wider text-muted mb-2">
              Render mode
            </h3>
            <div className="grid grid-cols-2 gap-1">
              {RENDER_MODES.map((mode) => (
                <label
                  key={mode}
                  className="flex items-center gap-2 text-sm cursor-pointer hover:text-fg"
                >
                  <input
                    type="checkbox"
                    checked={filters.renderModes.has(mode)}
                    onChange={() => toggleMode(mode)}
                    className="h-4 w-4 accent-accent"
                  />
                  <span>{mode.replace("_", " ")}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Toggles ---------------------------------------------------- */}
          <section className="space-y-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer hover:text-fg">
              <input
                type="checkbox"
                checked={filters.onlyWithEmotionTags}
                onChange={(e) =>
                  patch({ onlyWithEmotionTags: e.target.checked })
                }
                className="h-4 w-4 accent-accent"
              />
              <span>Only segments with emotion tags</span>
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer hover:text-fg">
              <input
                type="checkbox"
                checked={filters.onlyWithNotes}
                onChange={(e) => patch({ onlyWithNotes: e.target.checked })}
                className="h-4 w-4 accent-accent"
              />
              <span>Only segments with notes / flagged</span>
            </label>
          </section>
        </div>

        {/* Footer -------------------------------------------------------- */}
        <div className="border-t border-border px-4 py-3 shrink-0 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="btn-primary min-h-tap px-4 text-sm"
          >
            Apply
          </button>
        </div>
      </aside>
    </>
  );
}

// Guard against tree-shaking of the default export when only the type
// helpers get imported elsewhere.
void EMPTY_FILTERS;
