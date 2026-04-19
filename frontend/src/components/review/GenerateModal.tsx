import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  api,
  type GenerationEstimate,
  type VoiceboxHealth,
} from "../../lib/api";
import { useToast } from "../../lib/toast";

interface Props {
  open: boolean;
  onClose: () => void;
  chapterId: string;
  estimate: GenerationEstimate | undefined;
  voiceboxHealth: VoiceboxHealth | undefined;
}

export default function GenerateModal({
  open,
  onClose,
  chapterId,
  estimate,
  voiceboxHealth,
}: Props) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // Autofocus Cancel on open so Esc/Enter have a stable target; Enter will
  // still submit via the keydown handler below.
  useEffect(() => {
    if (open) {
      setBusy(false);
      // Next tick so the node exists.
      setTimeout(() => cancelRef.current?.focus(), 0);
    }
  }, [open]);

  const reachable = !!(voiceboxHealth?.enabled && voiceboxHealth.reachable);
  const disabledState: "none" | "unreachable" | "disabled" = !voiceboxHealth
    ? "none"
    : !voiceboxHealth.enabled
      ? "disabled"
      : !voiceboxHealth.reachable
        ? "unreachable"
        : "none";

  const canGenerate = reachable && (estimate?.segments ?? 0) > 0 && !busy;

  async function doGenerate() {
    if (!canGenerate) return;
    setBusy(true);
    try {
      const result = await api.generateChapter(chapterId);
      toast({
        kind: "success",
        message: `Generating ${result.segment_count} segment${
          result.segment_count === 1 ? "" : "s"
        }…`,
      });
      qc.invalidateQueries({ queryKey: ["gen-status", chapterId] });
      qc.invalidateQueries({ queryKey: ["segments", chapterId] });
      onClose();
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Failed to start generation.";
      toast({ kind: "error", message });
      setBusy(false);
    }
  }

  async function doRetryHealth() {
    await qc.invalidateQueries({ queryKey: ["voicebox-health"] });
  }

  // Key handling: Esc → close; Enter → submit (only when allowed).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Enter") {
        // Only submit if focus isn't inside an interactive input other than
        // the dialog's own buttons. We scope loosely here and just require
        // the dialog to be open.
        if (canGenerate) {
          e.preventDefault();
          void doGenerate();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, canGenerate]);

  if (!open) return null;

  const segmentCount = estimate?.segments ?? 0;
  const timeLabel = estimate?.human_label ?? "—";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Generate audio"
      className="fixed inset-0 z-50 bg-bg/70 backdrop-blur flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="card p-5 w-full max-w-[480px] space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-fg">
          Generate audio for this chapter
        </h2>

        <p className="text-sm text-fg/90">
          Generate audio for{" "}
          <strong className="text-fg">{segmentCount}</strong> segment
          {segmentCount === 1 ? "" : "s"}. Estimated time:{" "}
          <strong className="text-fg">~{timeLabel}</strong>. Voicebox must be
          running.
        </p>

        {/* Voicebox health callout ------------------------------------- */}
        {disabledState === "none" && voiceboxHealth && (
          <div
            className="chip text-[11px] inline-flex items-center gap-1.5"
            style={{ color: "#10B981", borderColor: "#10B981" }}
          >
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: "#10B981" }}
            />
            Voicebox online
            {voiceboxHealth.version ? ` (v${voiceboxHealth.version})` : ""}
          </div>
        )}

        {disabledState === "unreachable" && voiceboxHealth && (
          <div className="space-y-2">
            <div
              className="chip text-[11px] inline-flex items-center gap-1.5"
              style={{ color: "#EF4444", borderColor: "#EF4444" }}
            >
              <span
                aria-hidden="true"
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: "#EF4444" }}
              />
              Voicebox not reachable at {voiceboxHealth.base_url}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={doRetryHealth}
                className="btn-surface min-h-tap text-xs"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {disabledState === "disabled" && (
          <div
            className="chip text-[11px] inline-flex items-center gap-1.5"
            style={{ color: "#F59E0B", borderColor: "#F59E0B" }}
          >
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: "#F59E0B" }}
            />
            Voicebox disabled (VOICEBOX_ENABLED=false) — generation will fail
          </div>
        )}

        {!voiceboxHealth && (
          <div className="text-[11px] text-muted">
            Checking Voicebox status…
          </div>
        )}

        {/* Buttons ------------------------------------------------------ */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onClose}
            className="btn-ghost min-h-tap text-xs"
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={doGenerate}
            disabled={!canGenerate}
            className="btn-primary min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              !reachable
                ? "Voicebox must be online to generate"
                : segmentCount === 0
                  ? "Nothing to generate"
                  : "Start generation"
            }
          >
            {busy ? "Starting…" : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
