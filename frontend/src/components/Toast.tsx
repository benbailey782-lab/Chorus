import { useToast, type Toast, type ToastKind } from "../lib/toast";

// Left-border color per kind. Keeps toasts readable on the dark surface
// without shouting at the user.
const BORDER_CLASS: Record<ToastKind, string> = {
  success: "border-l-success",
  error: "border-l-error",
  info: "border-l-accent",
};

export default function ToastContainer() {
  const { toasts, dismiss } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div
      // Top-right on desktop, full-width sticky top on mobile. `pointer-events-none`
      // on the outer wrapper so the toasts only intercept clicks on their own card.
      aria-live="polite"
      aria-atomic="true"
      className="fixed inset-x-0 top-0 z-40 flex flex-col gap-2 p-2 pointer-events-none
                 sm:left-auto sm:right-4 sm:top-4 sm:w-80 sm:p-0"
      style={{ paddingTop: "calc(0.5rem + env(safe-area-inset-top, 0px))" }}
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: () => void;
}) {
  return (
    <div
      role={toast.kind === "error" ? "alert" : "status"}
      className={`card pointer-events-auto flex items-start gap-2 px-3 py-2 border-l-4 ${
        BORDER_CLASS[toast.kind]
      }`}
    >
      <div className="flex-1 text-sm text-fg whitespace-pre-wrap break-words">
        {toast.message}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="min-h-tap min-w-tap text-muted hover:text-fg shrink-0
                   -mr-1 -my-1 px-2 text-xl leading-none"
      >
        ×
      </button>
    </div>
  );
}
