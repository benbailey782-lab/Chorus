import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
}

/**
 * Phase 5R Commit 6: surface which Voicebox model is loaded (if any) so
 * the user can tell at a glance whether the first-generate click will be
 * an instant hit (model already loaded) or a 2-4-minute cold load. This
 * is adjunct to the ModelLoadingBanner which shows progress *while* a
 * load is in-flight; this banner shows the steady-state summary.
 */
export default function VoiceboxStatusBanner() {
  const health = useQuery({
    queryKey: ["voicebox-health"],
    queryFn: api.voiceboxHealth,
    staleTime: 60_000,
  });

  // Only query models when Voicebox is reachable — no point probing an
  // unreachable server. `enabled` short-circuits the query; staleTime of
  // 30s matches the convention in §Phase-5 frontend conventions.
  const reachable = !!(health.data?.enabled && health.data?.reachable);
  const modelsQuery = useQuery({
    queryKey: ["voicebox-models"],
    queryFn: api.listVoiceboxModels,
    enabled: reachable,
    staleTime: 30_000,
  });

  if (!health.data) return null;
  const h = health.data;

  // Happy path — reachable and enabled → show a small muted line with the
  // extra details (version / profile count / engines / loaded model / GPU)
  // so the operator can confirm at a glance.
  if (h.enabled && h.reachable) {
    const bits: string[] = [h.base_url];
    if (h.version) bits.push(`v${h.version}`);

    const extras: string[] = [];
    if (h.profile_count !== null) extras.push(`${h.profile_count} profiles`);
    if (h.available_engines.length > 0)
      extras.push(`engines: ${h.available_engines.join(", ")}`);

    // Model + GPU line (Phase-5R Commit 6). The loaded model is derived
    // from /models, which may not yet have resolved — fall back to the
    // coarse `h.model_loaded` boolean in that window.
    const loadedModel = (modelsQuery.data ?? []).find((m) => m.loaded);
    const modelLine = loadedModel
      ? `${loadedModel.name} loaded`
      : h.model_loaded
        ? "model loaded"
        : "no model loaded";

    return (
      <div
        role="status"
        className="card border border-border bg-surface text-muted px-3 py-2 text-xs flex items-start gap-2"
      >
        <span
          aria-hidden="true"
          className="inline-block w-2 h-2 rounded-full mt-1.5 bg-accent"
        />
        <div className="flex-1">
          <div className="font-medium text-fg text-sm">Voicebox online</div>
          <div>{bits.join(" \u00b7 ")}</div>
          <div className="text-[11px] mt-0.5">{modelLine}</div>
          {extras.length > 0 && (
            <div className="text-[11px] mt-0.5">{extras.join(" \u00b7 ")}</div>
          )}
        </div>
      </div>
    );
  }

  // Not-reachable / not-configured / disabled paths. `configured` lets
  // us distinguish "no URL saved yet" from "URL saved but disabled".
  const notConfigured = !h.configured;
  const notEnabled = h.configured && !h.enabled;
  const unreachable = h.configured && h.enabled && !h.reachable;

  const tone: "warn" | "muted" = unreachable ? "warn" : "muted";
  const bar =
    tone === "warn"
      ? "border-warn/40 bg-warn/10 text-warn"
      : "border-border bg-surface text-muted";

  let label: string;
  let primaryNote: string;
  if (notConfigured) {
    label = "Voicebox not configured";
    primaryNote =
      "Voicebox: Not configured. Settings \u2192 Voicebox to set up.";
  } else if (notEnabled) {
    label = "Voicebox disabled";
    primaryNote = "Voicebox: Configured but disabled.";
  } else {
    // unreachable branch
    label = "Voicebox unreachable";
    primaryNote = h.error
      ? `Voicebox: Unreachable at ${h.base_url}. ${truncate(h.error, 80)}`
      : `Voicebox: Unreachable at ${h.base_url}.`;
  }

  return (
    <div
      role="status"
      className={`card border ${bar} px-3 py-2 text-xs flex items-start gap-2`}
    >
      <span
        aria-hidden="true"
        className={`inline-block w-2 h-2 rounded-full mt-1.5 ${
          tone === "warn" ? "bg-warn" : "bg-muted"
        }`}
      />
      <div className="flex-1">
        <div className="font-medium text-fg text-sm">{label}</div>
        <div>{primaryNote}</div>
        <div className="text-[11px] mt-0.5">
          Metadata editing and reference-audio upload still work; TTS generation
          is disabled until Voicebox is online.
        </div>
      </div>
    </div>
  );
}
