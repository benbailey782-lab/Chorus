import { useEffect, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";

import { useToast } from "../../lib/toast";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  summary: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => Promise<void>;
}

/**
 * Shared confirmation modal for the four real bulk actions (reassign speaker,
 * set render mode, add tag, remove tag). Owns a useMutation that wraps
 * `onConfirm` so the parent just returns a promise and doesn't have to worry
 * about spinner state.
 *
 * On success: closes the modal. On error: keeps modal open so the operator
 * can retry. Both cases surface via toast.
 */
export default function BulkConfirmModal({
  open,
  onClose,
  title,
  summary,
  confirmLabel = "Apply",
  destructive = false,
  onConfirm,
}: Props) {
  const { toast } = useToast();

  const mutation = useMutation({
    mutationFn: async () => {
      await onConfirm();
    },
    onSuccess: () => {
      onClose();
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error && err.message ? err.message : "Action failed.";
      toast({ kind: "error", message });
    },
  });

  // Escape to dismiss (disabled while the action is in flight so the operator
  // can't accidentally lose their place mid-apply).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !mutation.isPending) {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, mutation.isPending]);

  if (!open) return null;

  const confirmClass = destructive ? "btn-danger" : "btn-primary";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-40 bg-bg/80 backdrop-blur flex items-center
                 justify-center px-4 py-6"
      onClick={() => {
        if (!mutation.isPending) onClose();
      }}
    >
      <div
        className="card max-w-md w-full p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-display text-lg">{title}</h2>
          <button
            type="button"
            className="min-h-tap min-w-tap text-muted hover:text-fg text-xl leading-none disabled:opacity-40"
            onClick={onClose}
            disabled={mutation.isPending}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="text-sm text-fg/90">{summary}</div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
            className="btn-ghost min-h-tap text-xs disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className={`${confirmClass} min-h-tap text-xs disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center gap-2`}
          >
            {mutation.isPending && (
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="animate-spin"
              >
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            )}
            {mutation.isPending ? "Applying\u2026" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
