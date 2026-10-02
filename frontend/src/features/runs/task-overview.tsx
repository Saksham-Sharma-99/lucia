import { useQuery } from "@tanstack/react-query";
import {
  ArrowRightIcon,
  BotIcon,
  ListTodoIcon,
  MessageSquareTextIcon,
  SettingsIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { listConnectionsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { EpisodeOut, RunOut, StepOut, TaskOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { CopyField } from "@/components/shared/copy-field";
import { Markdown } from "@/components/shared/markdown";
import { dateTime } from "@/lib/format";
import { CONNECTOR_NAMES } from "@/lib/connectors";

import { duration, itemProgress, statusLabel } from "./model";
import { StatusPill } from "./status-pill";
import { connectorsOf, triggerOf, type PlanItem } from "./steps-model";

/** How the task ran, top to bottom: trigger → task → agent → connectors → output. */
export function TaskOverview({
  run,
  task,
  steps,
  episodes,
  onViewOutput,
}: {
  run: RunOut;
  task: TaskOut;
  steps: StepOut[];
  episodes: EpisodeOut[];
  onViewOutput: () => void;
}) {
  const connections = useQuery(listConnectionsOptions({ path: { firm_id: run.firm_id } }));
  const status = (name: string) =>
    connections.data?.find((c) => c.connector === name)?.status ?? "not connected";
  const connectors = connectorsOf(task, steps);
  const trigger = triggerOf(task, episodes);
  const { done, total } = itemProgress(task.plan as PlanItem[]);
  const summary = (task.output?.summary as string | undefined) ?? "";
  return (
    <div className="grid h-full md:grid-cols-[1fr_320px]">
      <section
        aria-label="How this task ran"
        className="flex flex-col items-center gap-0 overflow-y-auto px-6 py-8"
      >
        <div className="w-full max-w-md rounded-xl border border-dashed px-4 py-3 text-sm">
          <p className="text-primary flex items-center gap-1.5 font-medium">
            <MessageSquareTextIcon className="size-4" />
            {trigger ? statusLabel(trigger.trigger_type) : "Started"}
          </p>
          <p className="text-muted-foreground mt-1">
            {trigger?.reason ??
              (trigger?.source ? `From ${trigger.source}` : "The request that started this task")}
          </p>
        </div>
        <Arrow />
        <Node icon={<ListTodoIcon className="size-4" />} title={task.title}>
          <p className="text-muted-foreground">{task.goal}</p>
        </Node>
        <Arrow />
        <Node icon={<BotIcon className="size-4" />} title={`@${run.agent_handle}`} narrow>
          <p className="text-muted-foreground">v{run.version}</p>
        </Node>
        {connectors.length > 0 && (
          <>
            <Arrow />
            <div className="flex flex-wrap justify-center gap-3">
              {connectors.map((c) => (
                <div
                  key={c.name}
                  className="bg-card relative flex w-36 flex-col items-center gap-1.5 rounded-xl border px-3 py-3 text-center text-sm shadow-xs"
                >
                  <ConnectorIcon connector={c.name} className="size-9" />
                  <span className="font-medium">{CONNECTOR_NAMES[c.name] ?? c.name}</span>
                  <span className="text-muted-foreground text-xs">
                    {statusLabel(status(c.name))}
                  </span>
                  {c.calls > 0 && (
                    <span
                      aria-label={`${c.calls} call${c.calls === 1 ? "" : "s"}`}
                      className="bg-primary/10 text-primary absolute top-1.5 right-1.5 rounded-full px-1.5 text-xs font-semibold tabular-nums"
                    >
                      {c.calls}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
        <Arrow />
        <Node icon={<SettingsIcon className="size-4" />} title="Output">
          {summary ? (
            <Markdown className="text-foreground">{summary}</Markdown>
          ) : (
            <p className="text-muted-foreground">Not finished yet.</p>
          )}
          <button
            type="button"
            onClick={onViewOutput}
            className="text-primary mt-2 inline-flex items-center gap-1 text-sm font-medium hover:underline"
          >
            View output <ArrowRightIcon className="size-3.5" />
          </button>
        </Node>
      </section>
      <aside
        aria-label="Task details"
        className="space-y-0 overflow-y-auto border-t px-6 py-5 text-sm md:border-t-0 md:border-l"
      >
        <p className="font-medium">Goal</p>
        <p className="text-muted-foreground mt-1 mb-4">{task.goal}</p>
        <Row label="Status">
          <StatusPill status={task.status} />
        </Row>
        <Row label="Started">{dateTime(task.started_at ?? task.created_at)}</Row>
        <Row label="Duration">{duration(task.started_at, task.ended_at)}</Row>
        <Row label="Agent">@{run.agent_handle}</Row>
        <Row label="Items">
          {done}/{total}
        </Row>
        <Row label="Connectors">{connectors.length}</Row>
        <Row label="Output">{summary ? "1 result" : "—"}</Row>
        <Row label="Task key">
          <span className="font-mono text-xs">{task.key}</span>
        </Row>
        <div className="pt-4">
          <p className="mb-1 font-medium">Run ID</p>
          <CopyField value={run.id} label="Copy run ID" />
        </div>
      </aside>
    </div>
  );
}

function Node({
  icon,
  title,
  children,
  narrow,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  narrow?: boolean;
}) {
  return (
    <div
      className={`bg-card flex w-full gap-3 rounded-xl border px-4 py-3 text-sm shadow-xs ${narrow ? "max-w-xs" : "max-w-md"}`}
    >
      <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg border">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children}
      </div>
    </div>
  );
}

function Arrow() {
  return (
    <div aria-hidden className="flex flex-col items-center py-1">
      <span className="bg-foreground/40 h-6 w-px" />
      <span className="border-t-foreground/40 size-0 border-x-4 border-t-[6px] border-x-transparent" />
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t py-2.5">
      <span className="font-medium">{label}</span>
      <span className="text-muted-foreground text-right">{children}</span>
    </div>
  );
}
