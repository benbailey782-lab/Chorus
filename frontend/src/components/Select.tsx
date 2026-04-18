type Option<T extends string> = T | { value: T; label: string };

export default function Select<T extends string>({
  value,
  onChange,
  options,
  placeholder,
  disabled,
}: {
  value: T | null | undefined;
  onChange: (next: T | null) => void;
  options: readonly Option<T>[];
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <select
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange((e.target.value || null) as T | null)}
      className="input appearance-none"
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const label = typeof o === "string" ? labelize(o) : o.label;
        return (
          <option key={v} value={v}>
            {label}
          </option>
        );
      })}
    </select>
  );
}

function labelize(v: string): string {
  return v
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
