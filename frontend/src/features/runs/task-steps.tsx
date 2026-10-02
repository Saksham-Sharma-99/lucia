import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { listRunLogsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { StepOut, TaskOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CONNECTOR_NAMES } from "@/lib/connectors";
import { cn } from "@/lib/utils";

import { duration } from "./model";
import { StatusIcon, StatusPill } from "./status-pill";
import { CallArtifacts, Json } from "./step-detail";
import {
  attemptLabel,
  attemptsFor,
  keyArgs,
  replacedBy,
  subagentRounds,
  type PlanItem,
} from "./steps-model";

const STRUCK = ["SKIPPED", "SUPERSEDED"];
const time = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";

/** The task's plan items with their attempts (left), and the chosen one in detail (right). */
export function TaskSteps({
  runId,
  task,
  steps,
}: {
  runId: string;
  task: TaskOut;
  steps: StepOut[];
}) {
  const plan = [...(task.plan as PlanItem[])].sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0));
  const [selected, setSelected] = useState<{ item: string; step?: string }>({
    item: plan[0]?.id ?? "",
  });
  const item = plan.find((i) => i.id === selected.item);
  const attempts = item ? attemptsFor(item, steps) : [];
  const shown = attempts.find((s) => s.id === selected.step) ?? attempts.at(-1);
  if (plan.length === 0)
    return <p className="text-muted-foreground p-6 text-sm">The task hasn't been planned yet.</p>;
  return (
    <div className="grid h-full md:grid-cols-[340px_1fr]">
      <ol className="space-y-1 overflow-y-auto border-r p-3">
        {plan.map((i, index) => {
          const tries = attemptsFor(i, steps);
          const active = i.id === selected.item;
          const struck = STRUCK.includes(i.status ?? "");
          return (
            <li key={i.id}>
              <button
                type="button"
                title={struck ? (i.reason ?? undefined) : undefined}
                onClick={() => setSelected({ item: i.id })}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm",
                  active ? "bg-primary/10 ring-primary/30 ring-1" : "hover:bg-muted",
                )}
              >
                <StatusIcon status={i.status ?? "PENDING"} />
                <span className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full text-xs tabular-nums">
                  {i.ordinal ?? index + 1}
                </span>
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    active && "text-primary font-medium",
                    struck && "text-muted-foreground line-through",
                  )}
                >
                  {i.title}
                </span>
                <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                  {duration(tries[0]?.started_at, tries.at(-1)?.ended_at)}
                </span>
              </button>
              {i.status === "SUPERSEDED" &&
                replacedBy(i, plan).map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setSelected({ item: r.id })}
                    className="text-primary ml-16 text-xs hover:underline"
                  >
                    replaced by #{r.ordinal}
                  </button>
                ))}
              {tries.length > 0 && (
                <ul className="mt-0.5 ml-16 space-y-0.5">
                  {tries.map((s, n) =>
                    s.kind === "subagent" ? (
                      subagentRounds(s, steps).map((round, r) => (
                        <li key={`${s.id}-${r}`} className="text-muted-foreground text-xs">
                          {round.map((c) => c.role?.replace("sub_", "")).join(" → ")}
                          {reviewScore(round)}
                        </li>
                      ))
                    ) : (
                      <li key={s.id}>
                        <button
                          type="button"
                          onClick={() => setSelected({ item: i.id, step: s.id })}
                          className={cn(
                            "text-muted-foreground hover:text-foreground text-xs",
                            shown?.id === s.id && active && "text-foreground font-medium",
                          )}
                        >
                          {attemptLabel(s, n)}
                        </button>
                      </li>
                    ),
                  )}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
      {item && <StepPane runId={runId} item={item} step={shown} />}
    </div>
  );
}

function reviewScore(round: StepOut[]) {
  const score = round.find((c) => c.role === "sub_reviewer")?.output?.score;
  return typeof score === "number" ? ` (${score})` : "";
}

function StepPane({ runId, item, step }: { runId: string; item: PlanItem; step?: StepOut }) {
  const logs = useQuery({
    ...listRunLogsOptions({ path: { run_id: runId }, query: { step_id: step?.id } }),
    enabled: !!step,
  });
  const connector = (step?.tool ?? item.tool ?? "").split(".")[0];
  const status = step?.status ?? item.status ?? "PENDING";
  const policy = step?.output?.policy as { decision?: string; rule?: string } | undefined;
  return (
    <Tabs defaultValue="details" className="min-w-0 overflow-y-auto px-6 py-4">
      <TabsList variant="line">
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="input">Input</TabsTrigger>
        <TabsTrigger value="output">Output</TabsTrigger>
        <TabsTrigger value="logs">Logs ({logs.data?.length ?? 0})</TabsTrigger>
      </TabsList>
      <TabsContent value="details" className="space-y-4 pt-4">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold">
            Step {item.ordinal}: {item.title}
          </h3>
          <StatusPill status={status} />
          <span className="text-muted-foreground ml-auto text-sm">
            {duration(step?.started_at, step?.ended_at)}
          </span>
        </div>
        {item.input_hint && <p className="text-muted-foreground text-sm">{item.input_hint}</p>}
        {item.reason && STRUCK.includes(item.status ?? "") && (
          <p className="text-muted-foreground text-sm">Why: {item.reason}</p>
        )}
        <dl className="divide-y rounded-xl border text-sm">
          <Detail label="Action">{item.title}</Detail>
          <Detail label="Kind">{item.kind}</Detail>
          {connector && connector !== "harness" && (
            <Detail label="Connector">
              <span className="inline-flex items-center gap-2">
                <ConnectorIcon connector={connector} className="size-5" />
                {CONNECTOR_NAMES[connector] ?? connector}
              </span>
            </Detail>
          )}
          <Detail label="Time">
            {time(step?.started_at)} – {time(step?.ended_at)} (
            {duration(step?.started_at, step?.ended_at)})
          </Detail>
          <Detail label="Status">
            <StatusPill status={status} />
          </Detail>
          <Detail label="Model / Tool">{step?.model ?? step?.tool ?? item.tool ?? "—"}</Detail>
          {step && keyArgs(step.input) && <Detail label="Query">{keyArgs(step.input)}</Detail>}
          <Detail label="Summary">{step?.summary ?? item.output?.summary ?? "—"}</Detail>
          {policy?.decision && (
            <Detail label="Policy">
              {policy.decision}
              {policy.rule && ` · ${policy.rule}`}
            </Detail>
          )}
          {step?.error && (
            <Detail label="Error">
              {String(step.error.class ?? "")} {String(step.error.reason ?? "")}
            </Detail>
          )}
        </dl>
        {step && (
          <details className="rounded-xl border px-4 py-3 text-sm">
            <summary className="flex cursor-pointer items-center justify-between font-medium">
              Technical details <ChevronDownIcon className="size-4" />
            </summary>
            <dl className="text-muted-foreground mt-2 space-y-1 font-mono text-xs">
              <p>step {step.id}</p>
              {step.input_tokens != null && (
                <p>
                  tokens {step.input_tokens} in / {step.output_tokens} out
                </p>
              )}
            </dl>
          </details>
        )}
      </TabsContent>
      <TabsContent value="input" className="pt-4">
        <Json value={step?.input ?? {}} />
      </TabsContent>
      <TabsContent value="output" className="space-y-3 pt-4">
        {step?.tool === "vapi.place_call" && <CallArtifacts runId={runId} step={step} />}
        <Json value={step?.output ?? item.output ?? {}} />
      </TabsContent>
      <TabsContent value="logs" className="pt-4">
        {(logs.data ?? []).length === 0 ? (
          <p className="text-muted-foreground text-sm">No log lines for this step.</p>
        ) : (
          <ul className="divide-y rounded-xl border text-sm">
            {(logs.data ?? []).map((l) => (
              <li key={l.id} className="flex gap-3 px-3 py-2">
                <span className="text-muted-foreground tabular-nums">{time(l.at)}</span>
                <span className="text-muted-foreground uppercase">{l.level}</span>
                <span>{l.message}</span>
              </li>
            ))}
          </ul>
        )}
      </TabsContent>
    </Tabs>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[160px_1fr] gap-3 px-4 py-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
