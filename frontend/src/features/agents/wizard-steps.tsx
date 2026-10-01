import { useQuery } from "@tanstack/react-query";
import { CheckIcon, FileIcon } from "lucide-react";

import { listAgentsOptions } from "@/api/generated/@tanstack/react-query.gen";
import { Avatar } from "@/components/shared/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The wizard's step rail. Steps up to the current one can be revisited; later ones can't, and
 * none can while `disabled` (e.g. the AI is drafting).
 */
export function StepNav<S extends string>({
  steps,
  current,
  onStep,
  disabled = false,
}: {
  steps: { id: S; label: string }[];
  current: S;
  onStep: (s: S) => void;
  disabled?: boolean;
}) {
  const index = steps.findIndex((s) => s.id === current);
  return (
    <nav aria-label="Steps">
      <ol className="space-y-1">
        {steps.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              disabled={disabled || i > index}
              aria-current={s.id === current ? "step" : undefined}
              onClick={() => onStep(s.id)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm disabled:cursor-default",
                s.id === current
                  ? "bg-accent font-medium"
                  : "text-muted-foreground enabled:hover:text-foreground",
              )}
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border text-[11px] tabular-nums",
                  i < index && "border-brass bg-brass text-primary-foreground",
                  s.id === current && "border-brass text-brass",
                )}
              >
                {i < index ? <CheckIcon className="size-3" /> : i + 1}
              </span>
              {s.label}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** First step: pick a template to prefill from, or start blank. */
export function StartStep({
  onPick,
  onBlank,
}: {
  onPick: (handle: string) => void;
  onBlank: () => void;
}) {
  const templates = useQuery(
    listAgentsOptions({ query: { is_template: true, limit: 50, sort: "name" } }),
  );
  const card =
    "hover:border-brass/60 flex items-start gap-3 rounded-lg border p-4 text-left transition-colors";
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold">Start from a template</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          Every step is filled in from the template. You can change anything.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {templates.isPending
          ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-24" />)
          : templates.data?.items.map((t) => (
              <button key={t.id} type="button" onClick={() => onPick(t.handle)} className={card}>
                <Avatar label={t.name} colorKey={t.handle} />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{t.name}</span>
                  <span className="text-muted-foreground font-mono text-xs">@{t.handle}</span>
                  <span className="text-muted-foreground mt-1 line-clamp-2 block text-sm">
                    {t.description}
                  </span>
                </span>
              </button>
            ))}
        <button type="button" onClick={onBlank} className={cn(card, "border-dashed")}>
          <span className="bg-secondary flex size-8 items-center justify-center rounded-md">
            <FileIcon className="size-4" />
          </span>
          <span>
            <span className="block text-sm font-medium">Blank agent</span>
            <span className="text-muted-foreground text-sm">Start with an empty config.</span>
          </span>
        </button>
      </div>
    </div>
  );
}
