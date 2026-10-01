import type { DiffEntry } from "@/api/generated/types.gen";

const SECTION_LABEL: Record<string, string> = {
  system_prompt: "Prompt",
  models: "Models",
  capabilities: "Capabilities",
  follow_up: "Follow-up",
  recurrence: "Repeats",
  end_conditions: "Limits",
  policy_pack: "Policy rules",
  hitl: "When to ask a person",
  alert_policy: "Alerts",
  max_turns_per_episode: "Limits",
};

function show(value: unknown): string {
  if (value === null || value === undefined) return "none";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A version diff grouped by config section: additions, removals and before → after. */
export function DiffView({ entries }: { entries: DiffEntry[] }) {
  if (!entries.length)
    return <p className="text-muted-foreground text-sm">These versions have the same config.</p>;
  const groups = new Map<string, DiffEntry[]>();
  for (const e of entries) {
    const section = SECTION_LABEL[e.path.split("/")[1]] ?? e.path.split("/")[1];
    groups.set(section, [...(groups.get(section) ?? []), e]);
  }
  return (
    <div className="space-y-6">
      {[...groups].map(([section, items]) => (
        <section key={section}>
          <h3 className="mb-2 text-sm font-semibold">{section}</h3>
          <ul className="space-y-2">
            {items.map((e) => (
              <li key={e.path} className="rounded-md border px-3 py-2 text-sm">
                <code className="text-muted-foreground font-mono text-xs">{e.path}</code>
                <div className="mt-1 grid gap-1">
                  {e.op !== "add" && (
                    <p className="text-destructive break-words whitespace-pre-wrap">
                      <span aria-label="removed">− </span>
                      {show(e.before)}
                    </p>
                  )}
                  {e.op !== "remove" && (
                    <p className="text-success break-words whitespace-pre-wrap">
                      <span aria-label="added">+ </span>
                      {show(e.after)}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
