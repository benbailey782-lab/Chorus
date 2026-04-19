import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import BulkConfirmModal from "./BulkConfirmModal";
import {
  EMOTION_TAG_SUGGESTIONS,
  RENDER_MODES,
} from "../../lib/constants";
import {
  api,
  type RenderMode,
  type Segment,
  type SegmentCharacter,
} from "../../lib/api";
import { useToast } from "../../lib/toast";

interface Props {
  selectedIds: Set<string>;
  segments: Segment[];
  characters: SegmentCharacter[];
  onDone: () => void;
}

type PickerKind = "reassign" | "mode" | "add_tag" | "remove_tag";

const ARCHETYPE_RANK: Record<string, number> = {
  main: 0,
  supporting: 1,
  minor: 2,
  background: 3,
};

function archetypeRank(a: string | null | undefined): number {
  if (!a) return 99;
  const key = a.toLowerCase();
  return ARCHETYPE_RANK[key] ?? 98;
}

function renderModeLabel(m: RenderMode): string {
  switch (m) {
    case "prose":
      return "Prose";
    case "dialogue":
      return "Dialogue";
    case "epigraph":
      return "Epigraph";
    case "letter":
      return "Letter";
    case "poetry":
      return "Poetry";
    case "song_lyrics":
      return "Song lyrics";
    case "emphasis":
      return "Emphasis";
    case "thought":
      return "Thought";
    case "chapter_heading":
      return "Chapter heading";
    default:
      return m;
  }
}

export default function BulkActionsMenu({
  selectedIds,
  segments,
  characters,
  onDone,
}: Props) {
  const qc = useQueryClient();
  const { toast } = useToast();

  const [menuOpen, setMenuOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [picker, setPicker] = useState<PickerKind | null>(null);

  // Picker inputs live here so the confirm-modal can read the chosen value.
  const [pickedCharacterId, setPickedCharacterId] = useState<string | null>(
    null,
  );
  const [pickedMode, setPickedMode] = useState<RenderMode>("dialogue");
  const [newTag, setNewTag] = useState("");
  const [removeTags, setRemoveTags] = useState<Set<string>>(new Set());

  // Mobile detection — drives FAB vs. sticky bar. We initialise to false so
  // SSR / first paint match the desktop layout; the effect flips it when the
  // media query matches.
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Close dropdown on outside click / Escape.
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setMenuOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const selectedSegments = useMemo(
    () => segments.filter((s) => selectedIds.has(s.id)),
    [segments, selectedIds],
  );

  const sortedCharacters = useMemo(() => {
    const rows = [...characters];
    rows.sort((a, b) => {
      const ra = archetypeRank(a.character_archetype);
      const rb = archetypeRank(b.character_archetype);
      if (ra !== rb) return ra - rb;
      return a.name.localeCompare(b.name);
    });
    return rows;
  }, [characters]);

  // Union of tags across selected segments — used by "Remove tag" to show
  // only tags that are actually present in at least one selected segment.
  const tagsInSelection = useMemo(() => {
    const s = new Set<string>();
    for (const seg of selectedSegments) {
      for (const t of seg.emotion_tags ?? []) s.add(t);
    }
    return Array.from(s).sort();
  }, [selectedSegments]);

  // Derive the chapterId for cache invalidation. All selected segments share a
  // chapter; pull from the first.
  const chapterId = selectedSegments[0]?.chapter_id ?? null;

  function invalidate() {
    if (chapterId) {
      qc.invalidateQueries({ queryKey: ["segments", chapterId] });
    }
  }

  function openPicker(kind: PickerKind) {
    setMenuOpen(false);
    setSheetOpen(false);

    // Seed defaults per picker.
    if (kind === "reassign") setPickedCharacterId(null);
    if (kind === "mode") setPickedMode("dialogue");
    if (kind === "add_tag") setNewTag("");
    if (kind === "remove_tag") setRemoveTags(new Set());

    setPicker(kind);
  }

  function closeAll() {
    setPicker(null);
    setMenuOpen(false);
    setSheetOpen(false);
  }

  // ---- Action runners -----------------------------------------------------

  async function runReassign() {
    const ids = Array.from(selectedIds);
    const resp = await api.bulkReassignSegments({
      segment_ids: ids,
      changes: { character_id: pickedCharacterId },
    });
    invalidate();
    toast({
      kind: "success",
      message: `${resp.updated} segment${resp.updated === 1 ? "" : "s"} updated.`,
    });
    closeAll();
    onDone();
  }

  async function runSetMode() {
    const ids = Array.from(selectedIds);
    const resp = await api.bulkReassignSegments({
      segment_ids: ids,
      changes: { render_mode: pickedMode },
    });
    invalidate();
    toast({
      kind: "success",
      message: `${resp.updated} segment${resp.updated === 1 ? "" : "s"} updated.`,
    });
    closeAll();
    onDone();
  }

  // Add / remove tag can't go through bulk-reassign because the bulk endpoint
  // applies the SAME `emotion_tags` array to every selected segment (it would
  // overwrite per-segment tags). So we iterate locally and PATCH each segment
  // with its own newly-computed tag list.
  async function runAddTag() {
    const tag = newTag.trim();
    if (!tag) return;
    const results = await Promise.allSettled(
      selectedSegments.map((seg) => {
        const existing = seg.emotion_tags ?? [];
        const already = existing.some(
          (t) => t.toLowerCase() === tag.toLowerCase(),
        );
        const next = already ? existing : [...existing, tag];
        return api.updateSegment(seg.id, { emotion_tags: next });
      }),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;
    invalidate();
    toast({
      kind: failed === 0 ? "success" : "error",
      message:
        failed === 0
          ? `${ok} updated.`
          : `${ok} updated, ${failed} failed.`,
    });
    closeAll();
    onDone();
  }

  async function runRemoveTag() {
    if (removeTags.size === 0) return;
    const lowered = new Set(
      Array.from(removeTags).map((t) => t.toLowerCase()),
    );
    const results = await Promise.allSettled(
      selectedSegments.map((seg) => {
        const existing = seg.emotion_tags ?? [];
        const next = existing.filter(
          (t) => !lowered.has(t.toLowerCase()),
        );
        // Skip the PATCH if nothing changed to avoid burning an API call.
        if (next.length === existing.length) {
          return Promise.resolve(seg);
        }
        return api.updateSegment(seg.id, { emotion_tags: next });
      }),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;
    invalidate();
    toast({
      kind: failed === 0 ? "success" : "error",
      message:
        failed === 0
          ? `${ok} updated.`
          : `${ok} updated, ${failed} failed.`,
    });
    closeAll();
    onDone();
  }

  if (selectedIds.size === 0) return null;

  const count = selectedIds.size;

  // ---- Shared action list (desktop dropdown + mobile sheet) ---------------
  const actionItems: Array<{ key: PickerKind; label: string }> = [
    { key: "reassign", label: "Reassign speaker" },
    { key: "mode", label: "Set render mode" },
    { key: "add_tag", label: "Add emotion tag" },
    { key: "remove_tag", label: "Remove emotion tag" },
  ];

  return (
    <>
      {/* Desktop sticky selection bar --------------------------------- */}
      {!isMobile && (
        <div
          className="hidden sm:flex sticky top-[6.25rem] z-20 -mx-2 px-3 py-2
                     items-center gap-3 border border-border rounded-card
                     bg-surface-2/95 backdrop-blur shadow-md mb-2"
          role="region"
          aria-label="Bulk actions"
        >
          <span className="text-sm text-fg font-medium">
            {count} segment{count === 1 ? "" : "s"} selected
          </span>

          <div className="relative ml-auto" ref={dropdownRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="btn-primary min-h-tap text-xs inline-flex items-center gap-1"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              Actions <span aria-hidden="true">{"\u25BE"}</span>
            </button>
            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-1 w-52 card p-1 z-30"
              >
                {actionItems.map((a) => (
                  <button
                    key={a.key}
                    type="button"
                    role="menuitem"
                    onClick={() => openPicker(a.key)}
                    className="w-full text-left px-3 py-2 text-sm rounded hover:bg-white/5
                               min-h-tap"
                  >
                    {a.label}
                  </button>
                ))}
                <div className="h-px bg-border my-1" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onDone();
                  }}
                  className="w-full text-left px-3 py-2 text-sm rounded hover:bg-white/5
                             min-h-tap text-muted"
                >
                  Clear selection
                </button>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={onDone}
            className="btn-ghost min-h-tap text-xs"
          >
            Clear
          </button>
        </div>
      )}

      {/* Mobile FAB + bottom sheet ------------------------------------- */}
      {isMobile && (
        <>
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-label={`Bulk actions, ${count} selected`}
            className="sm:hidden fixed z-30 rounded-full bg-accent text-accent-fg
                       shadow-xl h-14 w-14 grid place-items-center font-semibold"
            style={{ bottom: "72px", right: "16px" }}
          >
            <span className="text-sm">{count}</span>
          </button>

          {sheetOpen && (
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Bulk actions"
              className="sm:hidden fixed inset-0 z-40 bg-bg/70 backdrop-blur flex items-end"
              onClick={() => setSheetOpen(false)}
            >
              <div
                className="w-full bg-bg border-t border-border rounded-t-card p-2 pb-6"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex justify-center py-2">
                  <span
                    aria-hidden="true"
                    className="block h-1 w-10 rounded-full bg-border"
                  />
                </div>
                <div className="px-3 pb-2 text-sm text-muted">
                  {count} segment{count === 1 ? "" : "s"} selected
                </div>
                <div className="space-y-1">
                  {actionItems.map((a) => (
                    <button
                      key={a.key}
                      type="button"
                      onClick={() => openPicker(a.key)}
                      className="w-full text-left px-4 py-3 text-sm rounded hover:bg-white/5 min-h-tap"
                    >
                      {a.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => {
                      setSheetOpen(false);
                      onDone();
                    }}
                    className="w-full text-left px-4 py-3 text-sm rounded hover:bg-white/5 min-h-tap text-muted"
                  >
                    Clear selection
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Picker + confirm modals --------------------------------------- */}
      {picker === "reassign" && (
        <BulkConfirmModal
          open={true}
          onClose={closeAll}
          title="Reassign speaker"
          summary={
            <div className="space-y-3">
              <p>
                Reassign {count} segment{count === 1 ? "" : "s"} to:
              </p>
              <select
                value={pickedCharacterId ?? ""}
                onChange={(e) =>
                  setPickedCharacterId(e.target.value || null)
                }
                className="input appearance-none"
                autoFocus
              >
                <option value="">Unattributed</option>
                {sortedCharacters.map((c) => {
                  const suffix = c.character_archetype
                    ? ` (${c.character_archetype})`
                    : "";
                  return (
                    <option key={c.id} value={c.id}>
                      {c.name}
                      {suffix}
                    </option>
                  );
                })}
              </select>
            </div>
          }
          confirmLabel="Reassign"
          onConfirm={runReassign}
        />
      )}

      {picker === "mode" && (
        <BulkConfirmModal
          open={true}
          onClose={closeAll}
          title="Set render mode"
          summary={
            <div className="space-y-3">
              <p>
                Set render mode for {count} segment
                {count === 1 ? "" : "s"} to:
              </p>
              <select
                value={pickedMode}
                onChange={(e) => setPickedMode(e.target.value as RenderMode)}
                className="input appearance-none"
                autoFocus
              >
                {RENDER_MODES.map((m) => (
                  <option key={m} value={m}>
                    {renderModeLabel(m)}
                  </option>
                ))}
              </select>
            </div>
          }
          confirmLabel="Set mode"
          onConfirm={runSetMode}
        />
      )}

      {picker === "add_tag" && (
        <BulkConfirmModal
          open={true}
          onClose={closeAll}
          title="Add emotion tag"
          summary={
            <div className="space-y-3">
              <p>
                Add a tag to {count} segment{count === 1 ? "" : "s"} (existing
                tags are preserved).
              </p>
              <input
                type="text"
                list="bulk-add-tag-suggestions"
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                placeholder="Tag name (e.g. whispered)"
                className="input"
                autoFocus
              />
              <datalist id="bulk-add-tag-suggestions">
                {EMOTION_TAG_SUGGESTIONS.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
              {newTag.trim() === "" && (
                <p className="text-[11px] text-muted">
                  Enter a tag name to enable Apply.
                </p>
              )}
            </div>
          }
          confirmLabel="Add tag"
          onConfirm={runAddTag}
        />
      )}

      {picker === "remove_tag" && (
        <BulkConfirmModal
          open={true}
          onClose={closeAll}
          title="Remove emotion tag"
          summary={
            <div className="space-y-3">
              {tagsInSelection.length === 0 ? (
                <p className="text-muted">
                  None of the selected segments have emotion tags.
                </p>
              ) : (
                <>
                  <p>Select tags to remove from the {count} selected segments:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {tagsInSelection.map((t) => {
                      const on = removeTags.has(t);
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() =>
                            setRemoveTags((cur) => {
                              const next = new Set(cur);
                              if (next.has(t)) next.delete(t);
                              else next.add(t);
                              return next;
                            })
                          }
                          className={`chip text-[11px] ${
                            on
                              ? "border-accent text-accent"
                              : "text-muted hover:text-fg"
                          }`}
                          aria-pressed={on}
                        >
                          {on ? "\u2713 " : ""}
                          {t}
                        </button>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          }
          confirmLabel="Remove"
          destructive
          onConfirm={runRemoveTag}
        />
      )}
    </>
  );
}
