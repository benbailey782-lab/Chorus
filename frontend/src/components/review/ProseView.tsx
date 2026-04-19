import { useEffect, useRef } from "react";

import { CONFIDENCE } from "../../lib/constants";
import type { RenderMode, Segment } from "../../lib/api";

interface Props {
  segments: Segment[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

// Render-mode → container class. Prose is the baseline; other modes layer
// typography differences on top (indent, italic, scale).
function modeClasses(mode: RenderMode): string {
  switch (mode) {
    case "chapter_heading":
      return "font-display text-2xl mt-8 mb-4";
    case "thought":
      return "italic pl-4 text-fg/90";
    case "epigraph":
    case "letter":
    case "poetry":
    case "song_lyrics":
      return "italic pl-6 text-sm text-fg/90";
    case "emphasis":
      return "italic";
    case "dialogue":
      return "";
    case "prose":
    default:
      return "";
  }
}

// For dialogue: add quotes if the segment text isn't already quoted. LLM
// output usually already includes them, but we don't want to drop quotes if
// they were stripped somewhere upstream.
function ensureQuoted(text: string): string {
  const t = text.trim();
  if (!t) return text;
  const firstChar = t[0];
  const lastChar = t[t.length - 1];
  const isQuoted =
    (firstChar === '"' && lastChar === '"') ||
    (firstChar === "\u201c" && lastChar === "\u201d") ||
    (firstChar === "'" && lastChar === "'");
  return isQuoted ? text : `"${text}"`;
}

export default function ProseView({ segments, selectedId, onSelect }: Props) {
  // Scroll the selected segment into view when selection changes via
  // keyboard — without this, pressing j/k off-screen doesn't follow.
  const containerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!selectedId || !containerRef.current) return;
    const node = containerRef.current.querySelector<HTMLElement>(
      `[data-segment-id="${selectedId}"]`,
    );
    if (node) {
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedId]);

  return (
    <div ref={containerRef} className="space-y-2 pb-6">
      {segments.map((seg, i) => {
        const prev = i > 0 ? segments[i - 1] : null;
        const speaker = seg.character?.name ?? "Narration";
        const prevSpeaker = prev ? prev.character?.name ?? "Narration" : null;
        const showSpeaker = speaker !== prevSpeaker;

        const selected = seg.id === selectedId;
        const confidenceHex = CONFIDENCE.hexFor(seg.confidence);
        const borderColor = selected ? "#4EC8BE" : confidenceHex;
        const borderWidth = selected ? 6 : 4;

        const displayText =
          seg.render_mode === "dialogue" ? ensureQuoted(seg.text) : seg.text;

        return (
          <div key={seg.id}>
            {showSpeaker && (
              <div
                className="mt-4 mb-1 text-[11px] uppercase tracking-wider text-muted
                           font-mono flex items-center gap-2"
              >
                <span>{speaker}</span>
                {seg.text_modified && (
                  <span
                    className="text-muted/80 normal-case"
                    title="Text modified by operator"
                    aria-label="Text modified by operator"
                  >
                    {"\u270E Edited"}
                  </span>
                )}
              </div>
            )}
            <div
              role="button"
              tabIndex={0}
              aria-selected={selected}
              data-segment-id={seg.id}
              onClick={() => onSelect(seg.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(seg.id);
                }
              }}
              className={`cursor-pointer transition-colors rounded-sm
                          py-1 pr-2 ${selected ? "bg-white/5" : "hover:bg-white/[0.02]"}`}
              style={{
                borderLeftStyle: "solid",
                borderLeftColor: borderColor,
                borderLeftWidth: `${borderWidth}px`,
                paddingLeft: "16px",
              }}
            >
              <p
                className={`${modeClasses(seg.render_mode)} leading-relaxed
                            text-[15px] whitespace-pre-wrap`}
              >
                {displayText}
              </p>
              {seg.text_modified && (
                <span
                  className="mt-1 inline-block text-[10px] uppercase tracking-wider
                             text-warn"
                >
                  edited
                </span>
              )}
            </div>
          </div>
        );
      })}
      {segments.length === 0 && (
        <p className="text-muted text-sm italic">No segments yet.</p>
      )}
    </div>
  );
}
