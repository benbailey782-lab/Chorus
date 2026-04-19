/**
 * Phase 5R Commit 6 — global Voicebox model loading banner.
 *
 * Mounted in <Layout /> so it's visible from any page that might trigger
 * a model load. Activates when `useModelLoadingStore`'s `modelName` is
 * non-null. Polls `/api/voicebox/models/{name}/progress` every 1s and
 * renders a thin progress bar at the top of the main content area.
 *
 * Terminal states:
 *   - status `complete`/`loaded` → fire `onComplete`, briefly flash a
 *     "Model loaded" success line for ~1s, then clear `modelName` so
 *     the banner unmounts.
 *   - status `error` → fire `onError`, render in an error tone with a
 *     Dismiss button. The user clears it manually so they can read the
 *     message.
 *
 * Aesthetic matches PendingJobsBanner: card + colored border tone, accent
 * color for the progress bar fill.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useModelLoadingStore } from "../../stores/modelLoadingStore";

interface Props {
  /** Voicebox model name to track. `null` hides the banner entirely. */
  modelName: string | null;
  /** Fired once when status becomes terminal-success
   * (`complete` / `loaded` / `ready`). The banner still shows a brief
   * "✓ Model loaded" flash before unmounting itself. */
  onComplete?: () => void;
  /** Fired once when status becomes `error`/`failed`. The banner stays
   * visible until the user dismisses it. */
  onError?: (message: string) => void;
}

const TERMINAL_OK = new Set(["complete", "completed", "loaded", "ready", "done"]);
const TERMINAL_ERR = new Set(["error", "failed", "errored"]);

function modelLabel(name: string): string {
  // Voicebox model names like `qwen-tts-1.7B` are already operator-friendly.
  // Just trim and surface as-is for now.
  return name;
}

export default function ModelLoadingBanner({
  modelName,
  onComplete,
  onError,
}: Props): JSX.Element | null {
  const setModelName = useModelLoadingStore((s) => s.setModelName);

  // Once we hit a terminal state we stop polling and remember it locally
  // so we can flash the success line / pin the error message without the
  // store flipping back to "loading" on a stale poll.
  const [terminal, setTerminal] = useState<"ok" | "err" | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  // Reset terminal flag whenever the tracked model changes (e.g. user
  // dismisses one error then triggers a fresh load for the same/another
  // model). Without this, the success/error flash from a prior load
  // would survive into the next.
  useEffect(() => {
    setTerminal(null);
    setErrMsg(null);
  }, [modelName]);

  const enabled = !!modelName && terminal === null;

  const progressQuery = useQuery({
    queryKey: ["voicebox-model-progress", modelName],
    queryFn: () => {
      if (!modelName) throw new Error("no model");
      return api.voiceboxModelProgress(modelName);
    },
    enabled,
    // 1s polling per spec. We deliberately don't use `staleTime` here
    // — every tick should hit the network so the % bar moves smoothly.
    refetchInterval: enabled ? 1000 : false,
    // Don't show stale progress from a prior load.
    gcTime: 0,
  });

  const data = progressQuery.data;

  // React to terminal status transitions. We fire callbacks once via the
  // local `terminal` flag, then for OK we also schedule the auto-dismiss.
  useEffect(() => {
    if (!data || terminal !== null) return;
    const status = (data.status || "").toLowerCase();
    if (TERMINAL_OK.has(status)) {
      setTerminal("ok");
      onComplete?.();
      // Brief success flash, then unmount via store clear.
      const t = setTimeout(() => setModelName(null), 1000);
      return () => clearTimeout(t);
    }
    if (TERMINAL_ERR.has(status)) {
      const m = data.message || "Model load failed.";
      setTerminal("err");
      setErrMsg(m);
      onError?.(m);
    }
  }, [data, terminal, onComplete, onError, setModelName]);

  if (!modelName) return null;

  // Determine display state. While polling: progress + spinner. On error:
  // red banner + Dismiss button. On OK: brief check + label.
  const status = (data?.status || "loading").toLowerCase();
  const pct = Math.round(((data?.progress ?? 0) * 100));
  const label = modelLabel(modelName);

  if (terminal === "err") {
    return (
      <div
        role="alert"
        className="card border border-error/40 bg-error/10 px-3 py-2 text-xs flex items-start gap-2"
      >
        <span
          aria-hidden="true"
          className="inline-block w-2 h-2 rounded-full mt-1.5 bg-error"
        />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-fg text-sm">
            Failed to load TTS model: {label}
          </div>
          <div className="text-[11px] mt-0.5 break-words">
            {errMsg ?? "Voicebox returned an error."}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setModelName(null)}
          className="btn-ghost min-h-tap text-xs"
          aria-label="Dismiss model-load error"
        >
          Dismiss
        </button>
      </div>
    );
  }

  if (terminal === "ok") {
    return (
      <div
        role="status"
        className="card border border-accent/40 bg-accent/10 px-3 py-2 text-xs flex items-start gap-2"
      >
        <span
          aria-hidden="true"
          className="inline-block w-2 h-2 rounded-full mt-1.5 bg-accent"
        />
        <div className="flex-1">
          <div className="font-medium text-fg text-sm">
            {"\u2713"} Model loaded: {label}
          </div>
        </div>
      </div>
    );
  }

  // Active loading state.
  // We surface the raw status verbatim ("loading"/"downloading") so the
  // user can see when Voicebox shifts from "downloading weights" to
  // "loading into VRAM" — both phases happen on a cold first run.
  return (
    <div
      role="status"
      aria-live="polite"
      className="card border border-warn/40 bg-warn/10 px-3 py-2 text-xs flex items-start gap-2"
    >
      <span
        aria-hidden="true"
        className="inline-block w-2 h-2 rounded-full mt-1.5 bg-warn animate-pulse"
      />
      <div className="flex-1 min-w-0">
        <div className="font-medium text-fg text-sm">
          {status === "downloading" ? "Downloading" : "Loading"} TTS model:{" "}
          {label} ({pct}%)
        </div>
        {data?.message && (
          <div className="text-[11px] text-muted mt-0.5 truncate">
            {data.message}
          </div>
        )}
        <div
          className="mt-1 h-1.5 w-full rounded-full bg-surface overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label={`Model load progress for ${label}`}
        >
          <div
            className="h-full bg-accent transition-[width] duration-300 ease-out"
            style={{ width: `${Math.max(2, pct)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
