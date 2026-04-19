import { useMemo } from "react";

import { CONFIDENCE } from "../../lib/constants";
import type { RenderMode, Segment } from "../../lib/api";

interface Props {
  segments: Segment[];
  lowConfidenceOnClick?: () => void;
}

// Render-mode vocabulary for the chip counts row. We display them in §6
// declaration order so the eye doesn't have to scan a shuffled list.
const RENDER_MODE_ORDER: RenderMode[] = [
  "prose",
  "dialogue",
  "epigraph",
  "letter",
  "poetry",
  "song_lyrics",
  "emphasis",
  "thought",
  "chapter_heading",
];

export default function StatusBar({ segments, lowConfidenceOnClick }: Props) {
  const stats = useMemo(() => {
    const byMode = new Map<RenderMode, number>();
    const bySpeaker = new Map<string, number>();
    let lowConfidence = 0;
    for (const s of segments) {
      byMode.set(s.render_mode, (byMode.get(s.render_mode) ?? 0) + 1);
      const speaker = s.character?.name ?? "Narration";
      bySpeaker.set(speaker, (bySpeaker.get(speaker) ?? 0) + 1);
      if (s.confidence !== null && s.confidence < CONFIDENCE.YELLOW_MIN) {
        lowConfidence += 1;
      }
    }
    const topSpeakers = [...bySpeaker.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
    return {
      byMode,
      topSpeakers,
      lowConfidence,
      total: segments.length,
    };
  }, [segments]);

  // Compact mobile rendering — we hide the less-urgent chip clusters under
  // md and let the full bar render above. Keeps the bar visible without
  // overwhelming the phone viewport.
  return (
    <div
      className="sticky bottom-0 z-20 border-t border-border bg-surface/95
                 backdrop-blur text-xs"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      <div className="max-w-5xl mx-auto px-3 py-2 flex items-center gap-3
                      flex-wrap">
        <span className="text-fg font-medium shrink-0">
          {stats.total} {stats.total === 1 ? "segment" : "segments"}
        </span>

        {stats.lowConfidence > 0 && (
          <button
            type="button"
            className="chip text-error border-error/40 hover:bg-error/10
                       disabled:opacity-60"
            onClick={lowConfidenceOnClick}
            disabled={!lowConfidenceOnClick}
          >
            {stats.lowConfidence} low-conf
          </button>
        )}

        <span className="hidden md:flex items-center gap-1.5 text-muted
                         flex-wrap">
          {RENDER_MODE_ORDER.filter((m) => (stats.byMode.get(m) ?? 0) > 0).map((m) => (
            <span
              key={m}
              className="chip text-[10px] uppercase tracking-wider"
              title={m}
            >
              {m.replace("_", " ")} · {stats.byMode.get(m)}
            </span>
          ))}
        </span>

        <span className="ml-auto hidden sm:flex items-center gap-2 text-muted
                         flex-wrap justify-end">
          {stats.topSpeakers.map(([name, count]) => (
            <span
              key={name}
              className="truncate max-w-[10rem]"
              title={`${name}: ${count}`}
            >
              {name} <span className="text-fg/70">({count})</span>
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}
