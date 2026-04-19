import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
}

export default function VoiceboxStatusBanner() {
  const health = useQuery({
    queryKey: ["voicebox-health"],
    queryFn: api.voiceboxHealth,
    staleTime: 60_000,
  });

  if (!health.data) return null;
  const h = health.data;

  // Happy path — reachable and enabled → show a small muted line with the
  // extra details (version / profile count / engines) so the operator can
  // confirm at a glance.
  if (h.enabled && h.reachable) {
    const bits: string[] = [h.base_url];
    if (h.version) bits.push(`v${h.version}`);
    const extras: string[] = [];
    if (h.profile_count !== null) extras.push(`${h.profile_count} profiles`);
    if (h.available_engines.length > 0)
      extras.push(`engines: ${h.available_engines.join(", ")}`);
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
          {extras.length > 0 && (
            <div className="text-[11px] mt-0.5">{extras.join(" \u00b7 ")}</div>
          )}
        </div>
      </div>
    );
  }

  const tone = h.enabled && !h.reachable ? "warn" : "muted";
  const bar =
    tone === "warn"
      ? "border-warn/40 bg-warn/10 text-warn"
      : "border-border bg-surface text-muted";
  const label =
    tone === "warn" ? "Voicebox unreachable" : "Voicebox offline";

  const primaryNote = h.enabled
    ? h.error
      ? `Voicebox enabled but unreachable at ${h.base_url}: ${truncate(h.error, 80)}`
      : `Voicebox enabled but unreachable at ${h.base_url}.`
    : `Voicebox not configured (VOICEBOX_ENABLED=false) \u2014 voice generation features disabled.`;

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
