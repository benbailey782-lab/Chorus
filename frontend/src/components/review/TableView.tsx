import { useMemo, useState } from "react";

import { CONFIDENCE } from "../../lib/constants";
import type { Segment } from "../../lib/api";
import { SegmentAudioIcon, getSegmentAudioState } from "./segment-audio";

interface Props {
  segments: Segment[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: (ids: string[]) => void;
  onClearSelection: () => void;
  onPlay?: (id: string) => void;
}

type SortKey = "order" | "speaker" | "mode" | "confidence";
type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

const PREVIEW_MAX = 80;

function truncate(s: string, n: number): string {
  const compact = s.replace(/\s+/g, " ").trim();
  return compact.length <= n ? compact : compact.slice(0, n - 1) + "\u2026";
}

function withAlpha(hex: string, alpha: number): string {
  // Accepts #RRGGBB — converts to rgba() with the given alpha [0,1].
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const r = parseInt(m[1].slice(0, 2), 16);
  const g = parseInt(m[1].slice(2, 4), 16);
  const b = parseInt(m[1].slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function compareSegments(a: Segment, b: Segment, key: SortKey): number {
  switch (key) {
    case "order":
      return a.order_index - b.order_index;
    case "speaker": {
      const an = (a.character?.name ?? "").toLowerCase();
      const bn = (b.character?.name ?? "").toLowerCase();
      if (an === bn) return a.order_index - b.order_index;
      // Empty speaker (narration) bubbles to end in asc.
      if (!an) return 1;
      if (!bn) return -1;
      return an < bn ? -1 : 1;
    }
    case "mode": {
      const am = a.render_mode;
      const bm = b.render_mode;
      if (am === bm) return a.order_index - b.order_index;
      return am < bm ? -1 : 1;
    }
    case "confidence": {
      const ac = a.confidence ?? -1;
      const bc = b.confidence ?? -1;
      if (ac === bc) return a.order_index - b.order_index;
      return ac - bc;
    }
  }
}

interface HeaderProps {
  label: string;
  sortKey?: SortKey;
  sort: SortState;
  onSort: (k: SortKey) => void;
  className?: string;
}

function Th({ label, sortKey, sort, onSort, className }: HeaderProps) {
  const active = sortKey && sort.key === sortKey;
  const arrow = active ? (sort.dir === "asc" ? "\u2191" : "\u2193") : "";
  const baseClass =
    "px-2 py-2 text-left text-[10px] font-semibold text-muted uppercase " +
    "tracking-wider select-none";
  if (!sortKey) {
    return <th className={`${baseClass} ${className ?? ""}`}>{label}</th>;
  }
  return (
    <th className={`${baseClass} ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="hover:text-fg inline-flex items-center gap-1"
      >
        <span>{label}</span>
        <span className="text-[9px] text-accent min-w-[0.5em]">{arrow}</span>
      </button>
    </th>
  );
}

export default function TableView({
  segments,
  selectedId,
  onSelect,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onPlay,
}: Props) {
  const [sort, setSort] = useState<SortState>({ key: "order", dir: "asc" });

  const sorted = useMemo(() => {
    const arr = [...segments];
    arr.sort((a, b) => compareSegments(a, b, sort.key));
    if (sort.dir === "desc") arr.reverse();
    return arr;
  }, [segments, sort]);

  function toggleSort(key: SortKey) {
    setSort((cur) =>
      cur.key === key
        ? { key, dir: cur.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  const allChecked =
    segments.length > 0 && selectedIds.size === segments.length;
  const someChecked = selectedIds.size > 0 && !allChecked;

  function handleHeaderCheckbox() {
    if (allChecked) {
      onClearSelection();
    } else {
      onSelectAll(segments.map((s) => s.id));
    }
  }

  if (segments.length === 0) {
    return (
      <p className="text-muted text-sm italic p-4">No segments to show.</p>
    );
  }

  return (
    <div className="overflow-x-auto -mx-2">
      <table className="table w-full text-sm border-collapse">
        <thead className="border-b border-border">
          <tr>
            <th className="px-2 py-2 w-8">
              <input
                type="checkbox"
                aria-label={allChecked ? "Deselect all" : "Select all"}
                checked={allChecked}
                ref={(el) => {
                  if (el) el.indeterminate = someChecked;
                }}
                onChange={handleHeaderCheckbox}
                className="h-4 w-4 cursor-pointer accent-accent"
              />
            </th>
            <Th
              label="#"
              sortKey="order"
              sort={sort}
              onSort={toggleSort}
              className="w-10"
            />
            <Th
              label="Speaker"
              sortKey="speaker"
              sort={sort}
              onSort={toggleSort}
              className="w-40"
            />
            <Th
              label="Mode"
              sortKey="mode"
              sort={sort}
              onSort={toggleSort}
              className="w-28"
            />
            <Th
              label="Conf"
              sortKey="confidence"
              sort={sort}
              onSort={toggleSort}
              className="w-16"
            />
            <Th label="Tags" sort={sort} onSort={toggleSort} className="w-40" />
            <Th label="Preview" sort={sort} onSort={toggleSort} />
            <Th label="Audio" sort={sort} onSort={toggleSort} className="w-12" />
            <Th label="Notes" sort={sort} onSort={toggleSort} className="w-10" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((seg) => {
            const speaker = seg.character?.name ?? "Narration";
            const isSelected = seg.id === selectedId;
            const isChecked = selectedIds.has(seg.id);
            const confHex = CONFIDENCE.hexFor(seg.confidence);
            const confBg = withAlpha(confHex, 0.15);
            const preview = truncate(seg.text, PREVIEW_MAX);
            const hasNotes = !!(seg.notes && seg.notes.trim().length > 0);

            const rowClass = [
              "cursor-pointer border-b border-border/60",
              isSelected
                ? "bg-accent/10 border-l-2 border-l-accent"
                : "hover:bg-white/5 border-l-2 border-l-transparent",
            ].join(" ");

            return (
              <tr
                key={seg.id}
                onClick={() => onSelect(seg.id)}
                className={rowClass}
                style={{
                  contentVisibility: "auto",
                  containIntrinsicSize: "48px",
                }}
              >
                <td
                  className="px-2 py-1.5 align-top"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select segment ${seg.order_index + 1}`}
                    checked={isChecked}
                    onChange={() => onToggleSelect(seg.id)}
                    className="h-4 w-4 cursor-pointer accent-accent"
                  />
                </td>
                <td className="px-2 py-1.5 align-top text-muted font-mono text-[11px]">
                  {seg.order_index + 1}
                </td>
                <td className="px-2 py-1.5 align-top">
                  <span
                    className={
                      seg.character
                        ? "text-fg"
                        : "text-muted italic"
                    }
                  >
                    {speaker}
                  </span>
                  {seg.text_modified && (
                    <span
                      className="ml-1 text-[10px] text-muted"
                      title="Text modified by operator"
                      aria-label="Text modified by operator"
                    >
                      {"\u270E"}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 align-top">
                  <span
                    className="chip text-[10px] uppercase tracking-wider"
                    title={seg.render_mode}
                  >
                    {seg.render_mode.replace("_", " ")}
                  </span>
                </td>
                <td
                  className="px-2 py-1.5 align-top text-[11px] font-mono font-semibold"
                  style={{ backgroundColor: confBg, color: confHex }}
                  title={
                    seg.confidence == null
                      ? "no confidence"
                      : `confidence ${seg.confidence}`
                  }
                >
                  {seg.confidence == null ? "\u2014" : seg.confidence}
                </td>
                <td className="px-2 py-1.5 align-top">
                  <div className="flex flex-wrap gap-1">
                    {(seg.emotion_tags ?? []).slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="chip text-[9px] uppercase tracking-wider"
                      >
                        {tag}
                      </span>
                    ))}
                    {(seg.emotion_tags?.length ?? 0) > 3 && (
                      <span className="text-[10px] text-muted">
                        +{(seg.emotion_tags?.length ?? 0) - 3}
                      </span>
                    )}
                  </div>
                </td>
                <td
                  className="px-2 py-1.5 align-top text-fg/90"
                  title={seg.text}
                >
                  {preview}
                </td>
                <td
                  className="px-2 py-1.5 align-middle text-center"
                  onClick={(e) => e.stopPropagation()}
                >
                  {(() => {
                    const audioState = getSegmentAudioState(seg);
                    const interactive =
                      audioState === "generated" || audioState === "approved";
                    return (
                      <button
                        type="button"
                        onClick={() => {
                          if (!interactive) return;
                          onSelect(seg.id);
                          onPlay?.(seg.id);
                        }}
                        disabled={!interactive}
                        className={`h-5 w-5 inline-grid place-items-center text-muted ${
                          interactive
                            ? "hover:text-accent cursor-pointer"
                            : "cursor-default"
                        }`}
                        aria-label="Segment audio"
                        title={
                          audioState === "none"
                            ? "No audio yet"
                            : audioState === "generating"
                              ? "Generating…"
                              : audioState === "error"
                                ? "Generation error"
                                : "Play audio"
                        }
                      >
                        <SegmentAudioIcon state={audioState} size={14} />
                      </button>
                    );
                  })()}
                </td>
                <td
                  className="px-2 py-1.5 align-top text-center"
                  title={hasNotes ? seg.notes ?? "" : ""}
                  aria-label={hasNotes ? "has notes" : ""}
                >
                  {hasNotes ? "\uD83D\uDCDD" : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
