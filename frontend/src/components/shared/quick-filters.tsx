export type QuickFilter<V extends string> = { value: V; label: string; count?: number };

/** One-click filters with their counts, e.g. All 11 · Ready 9 · Coming soon 2. */
export function QuickFilters<V extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: V;
  options: readonly QuickFilter<V>[];
  onChange: (value: V) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="bg-muted/40 inline-flex rounded-lg border p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className="text-muted-foreground aria-pressed:bg-background aria-pressed:text-foreground flex items-center gap-1.5 rounded-md px-3 py-1 text-sm aria-pressed:shadow-sm"
        >
          {o.label}{" "}
          {o.count !== undefined && (
            <span className="text-xs tabular-nums opacity-70">{o.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
