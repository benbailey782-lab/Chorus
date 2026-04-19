import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import TagInput from "../TagInput";
import {
  CONFIDENCE,
  EMOTION_TAG_SUGGESTIONS,
  RENDER_MODES,
} from "../../lib/constants";
import {
  api,
  type RenderMode,
  type Segment,
  type SegmentCharacter,
  type SegmentUpdate,
} from "../../lib/api";
import { useToast } from "../../lib/toast";

interface Props {
  segment: Segment | null;
  characters: SegmentCharacter[];
  onClose?: () => void;
  onSaved?: (updated: Segment) => void;
}

interface DetailDraft {
  text: string;
  character_id: string | null;
  render_mode: RenderMode;
  emotion_tags: string[];
  notes: string;
}

// Archetype ordering for speaker picker. Unknown/null ranks lowest so they
// appear at the bottom of their alphabetical group.
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

function draftFromSegment(seg: Segment | null): DetailDraft {
  if (!seg) {
    return {
      text: "",
      character_id: null,
      render_mode: "prose",
      emotion_tags: [],
      notes: "",
    };
  }
  return {
    text: seg.text,
    character_id: seg.character?.id ?? null,
    render_mode: seg.render_mode,
    emotion_tags: [...(seg.emotion_tags ?? [])],
    notes: seg.notes ?? "",
  };
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function draftsEqual(a: DetailDraft, b: DetailDraft): boolean {
  return (
    a.text === b.text &&
    a.character_id === b.character_id &&
    a.render_mode === b.render_mode &&
    a.notes === b.notes &&
    arraysEqual(a.emotion_tags, b.emotion_tags)
  );
}

// Build the PATCH body by diffing the draft against the initial draft. Only
// changed fields are sent. character_id is explicitly sent as `null` when the
// user picks Unattributed (to clear it server-side) rather than omitted.
function buildPatch(draft: DetailDraft, initial: DetailDraft): SegmentUpdate {
  const body: SegmentUpdate = {};
  if (draft.text !== initial.text) body.text = draft.text;
  if (draft.character_id !== initial.character_id) {
    body.character_id = draft.character_id;
  }
  if (draft.render_mode !== initial.render_mode) {
    body.render_mode = draft.render_mode;
  }
  if (!arraysEqual(draft.emotion_tags, initial.emotion_tags)) {
    body.emotion_tags = [...draft.emotion_tags];
  }
  if (draft.notes !== initial.notes) {
    body.notes = draft.notes === "" ? null : draft.notes;
  }
  return body;
}

function EmptyState() {
  return (
    <div className="h-full min-h-[240px] flex flex-col items-center justify-center text-muted text-sm">
      <svg
        width="40"
        height="40"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="opacity-50 mb-3"
        aria-hidden="true"
      >
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M7 9h10M7 13h10M7 17h6" />
      </svg>
      <p>Select a segment to view details.</p>
    </div>
  );
}

export default function DetailPanel({
  segment,
  characters,
  onClose,
  onSaved,
}: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const qc = useQueryClient();
  const { toast } = useToast();

  // Rebuild initialDraft whenever the selected segment's id or server-side
  // updated_at changes — the latter ensures we reset after a successful save
  // re-fetches the row.
  const initialDraft = useMemo(
    () => draftFromSegment(segment),
    // Depend on id + updated_at so a server refresh clears dirty state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [segment?.id, segment?.updated_at],
  );

  const [draft, setDraft] = useState<DetailDraft>(initialDraft);

  // Reset draft when initialDraft changes (new segment selected or saved).
  useEffect(() => {
    setDraft(initialDraft);
  }, [initialDraft]);

  const isDirty = useMemo(
    () => !draftsEqual(draft, initialDraft),
    [draft, initialDraft],
  );

  // Sort characters by archetype rank then alphabetical name. We build this
  // every render from the characters prop because its ordering upstream is
  // arbitrary.
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

  const mutation = useMutation({
    mutationFn: async (): Promise<Segment> => {
      if (!segment) throw new Error("No segment selected");
      const body = buildPatch(draft, initialDraft);
      return api.updateSegment(segment.id, body);
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["segments", updated.chapter_id] });
      toast({ kind: "success", message: "Segment saved." });
      // Reset draft from the authoritative server copy so dirty clears even
      // if the cache invalidation hasn't refetched yet.
      setDraft(draftFromSegment(updated));
      onSaved?.(updated);
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message ? err.message : "Save failed.";
      toast({ kind: "error", message });
    },
  });

  const save = useCallback(() => {
    if (!segment || !isDirty || mutation.isPending) return;
    mutation.mutate();
  }, [segment, isDirty, mutation]);

  const cancel = useCallback(() => {
    setDraft(initialDraft);
  }, [initialDraft]);

  // Ctrl/Cmd+Enter save while focus is inside the panel.
  useEffect(() => {
    if (!segment) return;
    const node = panelRef.current;
    if (!node) return;
    function onKey(e: globalThis.KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        const within = node?.contains(e.target as Node | null);
        if (!within) return;
        e.preventDefault();
        save();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [segment, save]);

  if (!segment) {
    return (
      <div ref={panelRef} className="h-full">
        <EmptyState />
      </div>
    );
  }

  const confidenceHex = CONFIDENCE.hexFor(segment.confidence);
  const confidenceLabel =
    segment.confidence == null ? "\u2014" : `${segment.confidence}%`;

  // Prevent Ctrl/Cmd+Enter save from double-firing when pressed in the text
  // textarea (the window-level listener already handles it). We just catch
  // here so the default newline doesn't insert.
  function onTextareaKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
    }
  }

  return (
    <div
      ref={panelRef}
      className="flex flex-col h-full min-h-0 text-sm"
      aria-label="Segment detail"
    >
      {/* Header row ----------------------------------------------------- */}
      <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-2 text-[11px] text-muted font-mono">
        <div className="flex items-center gap-2">
          <span>#{segment.order_index + 1}</span>
          {isDirty && (
            <span
              title="Unsaved changes"
              aria-label="Unsaved changes"
              className="inline-block h-2 w-2 rounded-full bg-warn"
              style={{ backgroundColor: "#F59E0B" }}
            />
          )}
          {segment.text_modified && (
            <span
              className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted"
              title="Text modified by operator"
            >
              <span aria-hidden="true">{"\u270E"}</span>
              <span>User-edited</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span title={segment.id}>ID {segment.id.slice(0, 8)}</span>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="btn-ghost min-h-tap min-w-tap text-xs"
              aria-label="Close detail panel"
              title="Close"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Scrollable body ------------------------------------------------- */}
      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-4">
        {/* Text -------------------------------------------------------- */}
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">
            Text
          </span>
          <textarea
            value={draft.text}
            onChange={(e) =>
              setDraft((d) => ({ ...d, text: e.target.value }))
            }
            onKeyDown={onTextareaKey}
            className="input min-h-[120px] resize-y font-serif text-[15px] leading-relaxed"
            spellCheck
          />
        </label>

        {/* Speaker ----------------------------------------------------- */}
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">
            Speaker
          </span>
          <select
            value={draft.character_id ?? ""}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                character_id: e.target.value || null,
              }))
            }
            className="input appearance-none"
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
        </label>

        {/* Render mode ------------------------------------------------- */}
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">
            Render mode
          </span>
          <select
            value={draft.render_mode}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                render_mode: e.target.value as RenderMode,
              }))
            }
            className="input appearance-none"
          >
            {RENDER_MODES.map((m) => (
              <option key={m} value={m}>
                {renderModeLabel(m)}
              </option>
            ))}
          </select>
        </label>

        {/* Emotion tags ------------------------------------------------ */}
        <div className="space-y-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">
            Emotion tags
          </span>
          <TagInput
            value={draft.emotion_tags}
            onChange={(next) =>
              setDraft((d) => ({ ...d, emotion_tags: next }))
            }
            placeholder="Add tag and press Enter…"
            suggestions={EMOTION_TAG_SUGGESTIONS}
          />
        </div>

        {/* Notes ------------------------------------------------------- */}
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">
            Notes
          </span>
          <textarea
            rows={3}
            value={draft.notes}
            onChange={(e) =>
              setDraft((d) => ({ ...d, notes: e.target.value }))
            }
            onKeyDown={onTextareaKey}
            placeholder="Optional director notes (delivery hints, blocking, etc.)"
            className="input resize-y"
          />
        </label>

        {/* Confidence + Preview --------------------------------------- */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="space-y-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">
              Confidence
            </span>
            <div>
              <span
                className="chip text-[11px] font-mono font-semibold"
                style={{
                  color: confidenceHex,
                  borderColor: confidenceHex,
                }}
                title={
                  segment.confidence == null
                    ? "No confidence reported"
                    : `Confidence ${segment.confidence}`
                }
              >
                {confidenceLabel}
              </span>
            </div>
          </div>
        </div>

        <button
          type="button"
          disabled
          title="Voicebox required (Phase 5)"
          className="btn-surface w-full min-h-tap opacity-60 cursor-not-allowed
                     inline-flex items-center justify-center gap-2"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polygon points="6 4 20 12 6 20 6 4" />
          </svg>
          Preview audio
        </button>
      </div>

      {/* Sticky save bar ------------------------------------------------ */}
      <div
        className="sticky bottom-0 left-0 right-0 border-t border-border
                   bg-bg/95 backdrop-blur px-4 py-3 flex items-center justify-end gap-2"
      >
        <button
          type="button"
          onClick={cancel}
          disabled={!isDirty || mutation.isPending}
          className="btn-ghost min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!isDirty || mutation.isPending}
          className="btn-primary min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
          title="Save (Ctrl/Cmd+Enter)"
        >
          {mutation.isPending ? "Saving\u2026" : "Save"}
        </button>
      </div>
    </div>
  );
}
