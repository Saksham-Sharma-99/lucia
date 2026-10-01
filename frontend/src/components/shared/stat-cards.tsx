import type { ReactNode } from "react";

export type Stat = { label: string; value: ReactNode };

/** Headline numbers above a list. A value still loading shows as a dash. */
export function StatCards({ stats }: { stats: Stat[] }) {
  return (
    <dl className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map((s) => (
        <div key={s.label} className="bg-card rounded-xl border px-4 py-3">
          <dt className="text-muted-foreground text-xs font-medium tracking-wider uppercase">
            {s.label}
          </dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums">{s.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
