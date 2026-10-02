import {
  BotIcon,
  DatabaseIcon,
  FileInputIcon,
  FileOutputIcon,
  PlugIcon,
  UserIcon,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { EpisodeOut, StepOut, TaskOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { Markdown } from "@/components/shared/markdown";
import { CONNECTOR_NAMES } from "@/lib/connectors";
import { dateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { statusLabel } from "./model";
import { StatusPill } from "./status-pill";
import { CallArtifacts, Json } from "./step-detail";
import { roleLabel, triggerOf, type PlanItem } from "./steps-model";

export type IOSection =
  "user" | "subagent-input" | "subagent-output" | `connector:${string}` | "intermediate" | "final";

/** What went into the task and what came out, by kind (docs/ui-refs/task-drawer-io.jpg). */
export function TaskIO({
  runId,
  task,
  steps,
  episodes,
  section,
  onSection,
}: {
  runId: string;
  task: TaskOut;
  steps: StepOut[];
  episodes: EpisodeOut[];
  section: IOSection;
  onSection: (s: IOSection) => void;
}) {
  const plan = [...(task.plan as PlanItem[])].sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0));
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const toolSteps = steps.filter(
    (s) => s.kind === "tool" && s.tool && !s.tool.startsWith("harness."),
  );
  const connectors = [...new Set(toolSteps.map((s) => s.tool!.split(".")[0]))];
  const trigger = triggerOf(task, episodes);
  const nav: { id: IOSection; label: string; icon: LucideIcon; child?: string }[] = [
    { id: "user", label: "User input", icon: UserIcon },
    { id: "subagent-input", label: "Subagent input", icon: BotIcon },
    { id: "subagent-output", label: "Subagent output", icon: FileOutputIcon },
    ...connectors.map((c) => ({
      id: `connector:${c}` as IOSection,
      label: CONNECTOR_NAMES[c] ?? c,
      icon: PlugIcon,
      child: c,
    })),
    { id: "intermediate", label: "Intermediate data", icon: DatabaseIcon },
    { id: "final", label: "Final output", icon: FileInputIcon },
  ];
  return (
    <div className="grid h-full md:grid-cols-[260px_1fr]">
      <nav className="space-y-0.5 border-r p-3">
        {nav.map((n, i) => (
          <div key={n.id}>
            {n.child && nav[i - 1] && !nav[i - 1].child && (
              <p className="text-muted-foreground flex items-center gap-2 px-3 pt-2 pb-1 text-sm">
                <PlugIcon className="size-4" /> Connector inputs
              </p>
            )}
            <button
              type="button"
              onClick={() => onSection(n.id)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm",
                n.child && "pl-8",
                section === n.id ? "bg-primary/10 text-primary font-medium" : "hover:bg-muted",
              )}
            >
              {n.child ? (
                <ConnectorIcon connector={n.child} className="size-5" />
              ) : (
                <n.icon className="size-4" />
              )}
              {n.label}
            </button>
          </div>
        ))}
      </nav>
      <div className="min-w-0 overflow-y-auto px-6 py-5">
        {section === "user" && (
          <Section title="User input">
            <div className="bg-muted/40 rounded-xl border p-4 text-sm">
              <p className="font-medium">Query</p>
              <p className="text-muted-foreground mt-1">{task.goal}</p>
            </div>
            <h4 className="mt-5 mb-2 text-sm font-medium">Context</h4>
            <dl className="divide-y rounded-xl border text-sm">
              <Row label="Trigger">{trigger ? statusLabel(trigger.trigger_type) : "—"}</Row>
              <Row label="Time">{dateTime(trigger?.created_at ?? task.created_at)}</Row>
              <Row label="Source">{trigger?.source ?? "Playground or Slack"}</Row>
              <Row label="Files">None</Row>
              <Row label="Task key">
                <span className="font-mono text-xs">{task.key}</span>
              </Row>
            </dl>
          </Section>
        )}
        {section === "subagent-input" && (
          <Section title="Subagent input">
            <ModelCalls steps={ordered} plan={plan} side="input" />
          </Section>
        )}
        {section === "subagent-output" && (
          <Section title="Subagent output">
            <ModelCalls steps={ordered} plan={plan} side="output" />
          </Section>
        )}
        {section.startsWith("connector:") && (
          <Section title={`${CONNECTOR_NAMES[section.slice(10)] ?? section.slice(10)} inputs`}>
            {toolSteps
              .filter((s) => s.tool!.startsWith(`${section.slice(10)}.`))
              .map((s) => (
                <div key={s.id} className="space-y-2">
                  <p className="text-muted-foreground text-xs">
                    {s.tool} · {dateTime(s.started_at)}
                  </p>
                  <Json value={s.input} />
                  {s.tool === "vapi.place_call" && <CallArtifacts runId={runId} step={s} />}
                </div>
              ))}
          </Section>
        )}
        {section === "intermediate" && (
          <Section title="Intermediate data">
            <ol className="space-y-3">
              {plan
                .filter((i) => i.output?.summary)
                .map((i) => (
                  <li key={i.id} className="rounded-xl border p-3 text-sm">
                    <p className="font-medium">
                      #{i.ordinal} {i.title}
                    </p>
                    <p className="text-muted-foreground mt-1">{i.output?.summary}</p>
                  </li>
                ))}
            </ol>
          </Section>
        )}
        {section === "final" && (
          <Section title="Final output">
            {task.output?.summary ? (
              <div className="rounded-xl border p-4">
                <Markdown>{task.output.summary as string}</Markdown>
              </div>
            ) : (
              <Nothing />
            )}
            {task.output && (
              <div className="mt-3">
                <Json value={task.output} />
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}

const MODEL_KINDS = ["llm", "subagent"];

/**
 * Every model call of the task in the order it happened (planner, executor, subagent rounds,
 * checks, summaries), with the tool calls between them, so what came before and after each
 * action is plain.
 */
function ModelCalls({
  steps,
  plan,
  side,
}: {
  steps: StepOut[];
  plan: PlanItem[];
  side: "input" | "output";
}) {
  if (!steps.some((s) => MODEL_KINDS.includes(s.kind))) return <Nothing />;
  return (
    <ol className="space-y-3">
      {steps.map((s) => {
        if (s.kind === "tool" && s.tool && !s.tool.startsWith("harness.")) {
          const [connector, action] = s.tool.split(".");
          return (
            <li key={s.id} className="text-muted-foreground flex items-center gap-2 pl-4 text-xs">
              <ConnectorIcon connector={connector} className="size-4" />
              then {CONNECTOR_NAMES[connector] ?? connector} · {action}
              <StatusPill status={s.status} />
            </li>
          );
        }
        if (!MODEL_KINDS.includes(s.kind)) return null;
        const label = s.kind === "subagent" ? "Subagent" : roleLabel(s.role);
        const it = plan.find((i) => i.id === s.plan_item_id);
        const value = side === "input" ? s.input : s.output;
        const text = side === "input" ? value?.message : value?.text;
        return (
          <li key={s.id} className={cn(s.parent_step_id && "pl-6")}>
            <article aria-label={label} className="space-y-2 rounded-xl border p-3">
              <header className="flex flex-wrap items-center gap-x-2 text-sm">
                <BotIcon className="text-primary size-4" />
                <span className="font-medium">{label}</span>
                {it && (
                  <span className="text-muted-foreground">
                    · #{it.ordinal} {it.title}
                  </span>
                )}
                <span className="text-muted-foreground ml-auto text-xs">
                  {dateTime(s.started_at)}
                  {s.model && ` · ${s.model}`}
                </span>
              </header>
              {typeof text === "string" ? (
                <pre className="bg-muted/50 max-h-[50vh] overflow-auto rounded-lg border p-3 font-sans text-sm whitespace-pre-wrap">
                  {text}
                </pre>
              ) : (
                <Json value={value ?? {}} />
              )}
            </article>
          </li>
        );
      })}
    </ol>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[200px_1fr] gap-3 px-4 py-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const Nothing = () => <p className="text-muted-foreground text-sm">Nothing here for this task.</p>;
