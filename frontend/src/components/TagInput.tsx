import { useState, type KeyboardEvent } from "react";

/**
 * Chip-style multi-value input used for tone, character_archetypes, tags.
 * Enter or comma commits the current buffer as a new chip; Backspace on an
 * empty buffer removes the last chip. Works without JS frameworks, 44px tap
 * targets, accessible labels on each chip's remove button.
 */
export default function TagInput({
  value,
  onChange,
  placeholder,
  suggestions,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  suggestions?: readonly string[];
}) {
  const [buffer, setBuffer] = useState("");

  const commit = (raw: string) => {
    const v = raw.trim();
    if (!v) return;
    if (value.some((x) => x.toLowerCase() === v.toLowerCase())) return;
    onChange([...value, v]);
    setBuffer("");
  };

  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx));

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit(buffer);
    } else if (e.key === "Backspace" && buffer === "" && value.length > 0) {
      e.preventDefault();
      remove(value.length - 1);
    }
  };

  const availableSuggestions = (suggestions ?? []).filter(
    (s) => !value.some((v) => v.toLowerCase() === s.toLowerCase()),
  );

  return (
    <div className="space-y-1.5">
      <div className="input flex flex-wrap items-center gap-1.5 py-2 min-h-tap">
        {value.map((v, i) => (
          <span key={`${v}-${i}`} className="chip pr-1 py-0.5">
            <span>{v}</span>
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => remove(i)}
              className="ml-1 w-5 h-5 rounded hover:bg-border text-muted hover:text-fg leading-none"
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={buffer}
          onChange={(e) => setBuffer(e.target.value)}
          onKeyDown={handleKey}
          onBlur={() => commit(buffer)}
          placeholder={value.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[8ch] bg-transparent text-fg placeholder-muted
                     focus:outline-none py-1"
        />
      </div>
      {availableSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {availableSuggestions.map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => commit(s)}
              className="chip hover:border-accent/60 text-muted hover:text-fg"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
