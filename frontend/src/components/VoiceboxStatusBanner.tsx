import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";

export default function VoiceboxStatusBanner() {
  const status = useQuery({
    queryKey: ["voicebox-status"],
    queryFn: api.voiceboxStatus,
    staleTime: 60_000,
  });

  if (!status.data) return null;
  const s = status.data;

  // Happy path — reachable and enabled → no banner noise.
  if (s.enabled && s.reachable) return null;

  const tone = s.enabled && !s.reachable ? "warn" : "muted";
  const bar =
    tone === "warn"
      ? "border-warn/40 bg-warn/10 text-warn"
      : "border-border bg-surface text-muted";
  const label =
    tone === "warn" ? "Voicebox unreachable" : "Voicebox offline";

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
        <div>{s.note}</div>
        <div className="text-[11px] mt-0.5">
          Metadata editing and reference-audio upload still work; TTS generation
          is disabled until Voicebox is online.
        </div>
      </div>
    </div>
  );
}
