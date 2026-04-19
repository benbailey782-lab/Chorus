import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastKind = "success" | "error" | "info";

export interface Toast {
  id: string;
  kind: ToastKind;
  message: string;
  ttl?: number;
}

export interface ToastInput {
  kind?: ToastKind;
  message: string;
  ttl?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  toast: (t: ToastInput) => string;
  dismiss: (id: string) => void;
}

const DEFAULT_TTL = 3000;

const ToastContext = createContext<ToastContextValue | null>(null);

function nextId(): string {
  // Cheap, collision-safe-enough for UI toast IDs.
  return (
    Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Per-toast timer handles so re-renders don't leak timeouts.
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const handle = timers.current.get(id);
    if (handle) {
      clearTimeout(handle);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (t: ToastInput): string => {
      const id = nextId();
      const entry: Toast = {
        id,
        kind: t.kind ?? "info",
        message: t.message,
        ttl: t.ttl ?? DEFAULT_TTL,
      };
      setToasts((prev) => [...prev, entry]);
      if (entry.ttl && entry.ttl > 0) {
        const handle = setTimeout(() => dismiss(id), entry.ttl);
        timers.current.set(id, handle);
      }
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const tmap = timers.current;
    return () => {
      for (const h of tmap.values()) clearTimeout(h);
      tmap.clear();
    };
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({ toasts, toast, dismiss }),
    [toasts, toast, dismiss],
  );

  return createElement(ToastContext.Provider, { value }, children);
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside a <ToastProvider>");
  }
  return ctx;
}
