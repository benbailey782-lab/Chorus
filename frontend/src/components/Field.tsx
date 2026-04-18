import { type ReactNode } from "react";

export function Field({
  label,
  hint,
  error,
  children,
  required,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="block text-sm space-y-1">
      <span className="block text-muted">
        {label}
        {required && <span className="text-accent"> *</span>}
      </span>
      {children}
      {hint && !error && <span className="block text-[11px] text-muted">{hint}</span>}
      {error && <span className="block text-[11px] text-error">{error}</span>}
    </label>
  );
}

export function FieldRow({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2">{children}</div>;
}
