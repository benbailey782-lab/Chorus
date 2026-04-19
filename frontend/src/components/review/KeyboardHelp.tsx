import { useEffect } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS: Array<[string, string]> = [
  ["\u2191 / \u2193  or  k / j", "navigate segments"],
  ["Enter", "open detail panel"],
  ["Esc", "close detail / clear / dismiss overlay"],
  ["Cmd/Ctrl + Enter", "save edit"],
  ["Cmd/Ctrl + A", "select all (table view)"],
  ["/", "focus filter bar"],
  ["?", "toggle this help"],
];

export default function KeyboardHelp({ open, onClose }: Props) {
  // Close on Escape at the modal level so the outer route handler doesn't
  // also react (it already ignores when focus is in an input; we explicitly
  // capture here to make dismissal reliable).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      className="fixed inset-0 z-30 bg-bg/80 backdrop-blur flex items-center
                 justify-center px-4 py-6"
      onClick={onClose}
    >
      <div
        className="card max-w-md w-full p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-xl">Keyboard shortcuts</h2>
          <button
            type="button"
            className="min-h-tap min-w-tap text-muted hover:text-fg text-xl leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <ul className="space-y-1.5 text-sm">
          {SHORTCUTS.map(([keys, label]) => (
            <li key={keys} className="flex items-baseline gap-3">
              <kbd
                className="font-mono text-xs px-2 py-0.5 border border-border rounded
                           bg-surface-2 text-fg shrink-0"
              >
                {keys}
              </kbd>
              <span className="text-muted">{label}</span>
            </li>
          ))}
        </ul>

        <p className="text-[11px] text-muted pt-1">
          Shortcuts are suppressed while focus is inside a text input.
        </p>
      </div>
    </div>
  );
}
