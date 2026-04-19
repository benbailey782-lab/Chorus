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
  type VoiceboxHealth,
} from "../../lib/api";
import { useToast } from "../../lib/toast";
import {
  SegmentAudioIcon,
  formatDurationMs,
  getSegmentAudioState,
  segmentAudioTitle,
  type SegmentAudioState,
} from "./segment-audio";

interface Props {
  segment: Segment | null;
  characters: SegmentCharacter[];
  voiceboxHealth?: VoiceboxHealth | undefined;
  /** When true, attempt to auto-play this segment's audio on mount/select. */
  autoPlay?: boolean;
  /** Called after an auto-play attempt so the parent can clear the flag. */
  onAutoPlayConsumed?: () => void;
  /** Chapter id for cache invalidation of generation queries. */
  chapterId?: string;
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
  voiceboxHealth,
  autoPlay,
  onAutoPlayConsumed,
  chapterId,
  onClose,
  onSaved,
}: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const qc = useQueryClient();
  const { toast } = useToast();
  const voiceboxReachable = !!(
    voiceboxHealth?.enabled && voiceboxHealth.reachable
  );

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

  // ---- Audio mutations (Phase 5) ---------------------------------------
  function invalidateAudio() {
    if (segment) {
      qc.invalidateQueries({ queryKey: ["segments", segment.chapter_id] });
    }
    if (chapterId) {
      qc.invalidateQueries({ queryKey: ["gen-status", chapterId] });
    }
  }

  const generateMut = useMutation({
    mutationFn: async () => {
      if (!segment) throw new Error("No segment selected");
      return api.generateSegment(segment.id);
    },
    onSuccess: () => {
      toast({ kind: "success", message: "Queued for generation." });
      invalidateAudio();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Failed to queue generation.";
      toast({ kind: "error", message });
    },
  });

  const regenerateMut = useMutation({
    mutationFn: async () => {
      if (!segment) throw new Error("No segment selected");
      return api.regenerateSegment(segment.id);
    },
    onSuccess: () => {
      toast({ kind: "success", message: "Regeneration queued." });
      invalidateAudio();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Failed to queue regeneration.";
      toast({ kind: "error", message });
    },
  });

  const approveMut = useMutation({
    mutationFn: async () => {
      if (!segment) throw new Error("No segment selected");
      return api.approveSegment(segment.id);
    },
    onSuccess: () => {
      toast({ kind: "success", message: "Audio approved." });
      invalidateAudio();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message ? err.message : "Approve failed.";
      toast({ kind: "error", message });
    },
  });

  const rejectMut = useMutation({
    mutationFn: async () => {
      if (!segment) throw new Error("No segment selected");
      return api.rejectSegment(segment.id);
    },
    onSuccess: () => {
      toast({ kind: "success", message: "Audio rejected." });
      invalidateAudio();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message ? err.message : "Reject failed.";
      toast({ kind: "error", message });
    },
  });

  // Phase-5R Commit 6: Retry hits `/retry` against the segment's prior
  // voicebox_generation_id. If the segment never had one (no
  // voicebox_generation_id yet), backend returns 400 — we fall back to
  // a fresh `generate` call so the user doesn't have to notice the
  // distinction.
  const retryMut = useMutation({
    mutationFn: async () => {
      if (!segment) throw new Error("No segment selected");
      try {
        return await api.retrySegment(segment.id);
      } catch (err) {
        // Backend: 400 when there's no prior generation to retry. Fall
        // back to a regular generate.
        const msg = err instanceof Error ? err.message : "";
        if (/^400\b/.test(msg)) {
          return api.generateSegment(segment.id);
        }
        throw err;
      }
    },
    onSuccess: () => {
      toast({ kind: "success", message: "Retry queued." });
      invalidateAudio();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message ? err.message : "Retry failed.";
      toast({ kind: "error", message });
    },
  });

  const cancel = useCallback(() => {
    setDraft(initialDraft);
  }, [initialDraft]);

  // When the parent asks us to auto-play (via `autoPlay` flag), fire play()
  // once the <audio> element exists. Consumed flag is cleared upstream.
  useEffect(() => {
    if (!autoPlay || !segment) return;
    const el = audioRef.current;
    if (!el) return;
    // Defer a tick so the src attribute is wired.
    const h = setTimeout(() => {
      el.play().catch(() => {
        /* autoplay blocked / no source — silent */
      });
      onAutoPlayConsumed?.();
    }, 0);
    return () => clearTimeout(h);
  }, [autoPlay, segment, onAutoPlayConsumed]);

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

        {/* Audio section (Phase 5) ----------------------------------- */}
        <AudioSection
          segment={segment}
          audioRef={audioRef}
          voiceboxReachable={voiceboxReachable}
          onGenerate={() => generateMut.mutate()}
          onRegenerate={() => regenerateMut.mutate()}
          onApprove={() => approveMut.mutate()}
          onReject={() => rejectMut.mutate()}
          onRetry={() => retryMut.mutate()}
          busy={{
            generate: generateMut.isPending,
            regenerate: regenerateMut.isPending,
            approve: approveMut.isPending,
            reject: rejectMut.isPending,
            retry: retryMut.isPending,
          }}
        />
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

// -----------------------------------------------------------------------
// Audio section — renders status badge, metadata, <audio>, and state-aware
// action buttons. Kept inside this module because it's coupled to DetailPanel
// lifecycle.
// -----------------------------------------------------------------------

interface AudioSectionProps {
  segment: Segment;
  audioRef: React.MutableRefObject<HTMLAudioElement | null>;
  voiceboxReachable: boolean;
  onGenerate: () => void;
  onRegenerate: () => void;
  onApprove: () => void;
  onReject: () => void;
  /** Phase-5R Commit 6: retry hits /segments/:id/retry against the prior
   * voicebox_generation_id. Distinct from onRegenerate which starts a
   * fresh generation from scratch. */
  onRetry: () => void;
  busy: {
    generate: boolean;
    regenerate: boolean;
    approve: boolean;
    reject: boolean;
    retry: boolean;
  };
}

function stateBadgeStyle(state: SegmentAudioState): {
  label: string;
  color: string;
} {
  switch (state) {
    case "approved":
      return { label: "Approved", color: "#10B981" };
    case "generated":
      return { label: "Generated", color: "#4EC8BE" };
    case "generating":
      return { label: "Generating…", color: "#F59E0B" };
    case "error":
      return { label: "Error", color: "#EF4444" };
    case "none":
    default:
      return { label: "No audio", color: "#6B6B70" };
  }
}

function AudioSection({
  segment,
  audioRef,
  voiceboxReachable,
  onGenerate,
  onRegenerate,
  onApprove,
  onReject,
  onRetry,
  busy,
}: AudioSectionProps) {
  const state = getSegmentAudioState(segment);
  const { label, color } = stateBadgeStyle(state);
  const audioUrl =
    state === "approved"
      ? `${api.segmentAudioUrl(segment.id, true)}?t=${encodeURIComponent(
          segment.updated_at,
        )}`
      : state === "generated" || state === "error"
        ? `${api.segmentAudioUrl(segment.id, false)}?t=${encodeURIComponent(
            segment.updated_at,
          )}`
        : null;
  const durationLabel = formatDurationMs(segment.duration_ms);

  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-[11px] uppercase tracking-wider text-muted">
          Audio
        </span>
        <span
          className="chip text-[10px] uppercase tracking-wider inline-flex items-center gap-1.5"
          style={{ color, borderColor: color }}
          title={segmentAudioTitle(state)}
        >
          <SegmentAudioIcon state={state} size={12} />
          {label}
        </span>
      </div>

      <div className="text-[11px] text-muted font-mono flex items-center gap-3 flex-wrap">
        {segment.updated_at && (
          <span title={`Last updated ${segment.updated_at}`}>
            {new Date(segment.updated_at).toLocaleString()}
          </span>
        )}
        {durationLabel && <span>{"\u00b7"} {durationLabel}</span>}
        {/* Phase-5R Commit 6: surface the Voicebox generation id so the
            operator can correlate a local segment with a Voicebox-side
            /generate/{id} record when debugging. Truncated to 8 chars +
            ellipsis; full id in the tooltip. Only shown once the
            segment has actually been generated/approved. */}
        {(state === "generated" || state === "approved") &&
          segment.voicebox_generation_id && (
            <span
              title={segment.voicebox_generation_id}
              className="truncate"
            >
              {"\u00b7"} vb:{segment.voicebox_generation_id.slice(0, 8)}
              {"\u2026"}
            </span>
          )}
      </div>

      {audioUrl && (
        <audio
          ref={audioRef}
          controls
          src={audioUrl}
          className="w-full"
          preload="metadata"
        />
      )}

      {state === "error" && segment.notes && (
        <p className="text-[11px] text-error">{segment.notes}</p>
      )}

      {/* Action buttons --------------------------------------------- */}
      <div className="flex flex-wrap gap-2 pt-1">
        {state === "none" && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={!voiceboxReachable || busy.generate}
            title={
              voiceboxReachable
                ? "Generate audio for this segment"
                : "Voicebox must be online"
            }
            className="btn-primary min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy.generate ? "Queuing…" : "Generate"}
          </button>
        )}

        {state === "generating" && (
          <span className="inline-flex items-center gap-2 text-xs text-muted">
            <SegmentAudioIcon state="generating" size={14} />
            Generating…
          </span>
        )}

        {(state === "generated" || state === "approved") && (
          <>
            <button
              type="button"
              onClick={() => audioRef.current?.play()}
              className="btn-surface min-h-tap text-xs"
              title="Play"
            >
              Play
            </button>
            {state === "generated" && (
              <button
                type="button"
                onClick={onApprove}
                disabled={busy.approve}
                className="btn-primary min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                title="Approve this take"
              >
                {busy.approve ? "Approving…" : "Approve"}
              </button>
            )}
            {state === "approved" && (
              <button
                type="button"
                onClick={onReject}
                disabled={busy.reject}
                className="btn-ghost min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                title="Clear approval"
              >
                {busy.reject ? "Rejecting…" : "Reject"}
              </button>
            )}
            <button
              type="button"
              onClick={onRegenerate}
              disabled={!voiceboxReachable || busy.regenerate}
              className="btn-ghost min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
              title={
                voiceboxReachable
                  ? "Generate a new take"
                  : "Voicebox must be online"
              }
            >
              {busy.regenerate ? "Queuing…" : "Regenerate"}
            </button>
          </>
        )}

        {state === "error" && (
          <button
            type="button"
            onClick={onRetry}
            disabled={!voiceboxReachable || busy.retry}
            className="btn-primary min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              voiceboxReachable
                ? "Retry the failed generation"
                : "Voicebox must be online"
            }
          >
            {busy.retry ? "Queuing\u2026" : "Retry"}
          </button>
        )}
      </div>
    </div>
  );
}
