import { useQuery } from "@tanstack/react-query";
import { ArrowRightIcon, BotIcon, ListTodoIcon, SettingsIcon } from "lucide-react";
import type { ReactNode } from "react";

import {
  listConnectionsOptions,
  listRunJournalOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { EpisodeOut, RunOut, StepOut, TaskOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { CopyField } from "@/components/shared/copy-field";
import { Markdown } from "@/components/shared/markdown";
import { dateTime } from "@/lib/format";
import { CONNECTOR_NAMES } from "@/lib/connectors";
import { cn } from "@/lib/utils";

import { duration, itemProgress, pollEvery, statusLabel } from "./model";
import { StatusIcon, StatusPill, TriggerIcon } from "./status-pill";
import {
  connectorsOf,
  flowRows,
  triggerOf,
  type FlowRow,
  type Note,
  type PlanItem,
} from "./steps-model";

/**
 * How the task ran, top to bottom: trigger → task → agent → connectors → each plan round and
 * its items → output. What happened (episodes, plan writes, calls, journal entries) sits to the
 * right, pointing at the node it concerns. Grows as the run polls.
 */
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
  const journal = useQuery({
    ...listRunJournalOptions({ path: { run_id: run.id } }),
    refetchInterval: pollEvery(run.status),
  });
  const status = (name: string) =>
    connections.data?.find((c) => c.connector === name)?.status ?? "not connected";
  const connectors = connectorsOf(task, steps);
  const trigger = triggerOf(task, episodes);
  const { done, total } = itemProgress(task.plan as PlanItem[]);
  const summary = (task.output?.summary as string | undefined) ?? "";
  const rows = flowRows(task, steps, episodes, journal.data?.entries);
  return (
    <div className="grid h-full md:grid-cols-[1fr_320px] md:grid-rows-[minmax(0,1fr)]">
      <section
        aria-label="How this task ran"
        className="min-h-0 overflow-y-auto bg-[radial-gradient(var(--border)_1px,transparent_1px)] [background-size:16px_16px] px-6 py-8"
      >
        <div className="mx-auto grid w-full max-w-4xl gap-x-10 md:grid-cols-[minmax(0,28rem)_minmax(0,1fr)]">
          <Line>
            <div className="bg-background w-full rounded-xl border border-dashed px-4 py-3 text-sm">
              <p className="text-primary flex items-center gap-1.5 font-medium">
                <TriggerIcon trigger={trigger?.trigger_type ?? "user_input"} className="size-4" />
                {trigger ? statusLabel(trigger.trigger_type) : "Started"}
              </p>
              <p className="text-muted-foreground mt-1">
                {trigger?.reason ??
                  (trigger?.source
                    ? `From ${trigger.source}`
                    : "The request that started this task")}
              </p>
            </div>
          </Line>
          <Line arrow>
            <Node icon={<ListTodoIcon className="size-4" />} title={task.title}>
              <p className="text-muted-foreground">{task.goal}</p>
            </Node>
          </Line>
          <Line arrow>
            <Node icon={<BotIcon className="size-4" />} title={`@${run.agent_handle}`} narrow>
              <p className="text-muted-foreground">v{run.version}</p>
            </Node>
          </Line>
          {connectors.length > 0 && (
            <Line arrow>
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
            </Line>
          )}
          {rows.map((row) => (
            <Line key={row.key} arrow notes={row.notes}>
              {row.item ? (
                <ItemNode item={row.item} />
              ) : (
                <Node icon={<ListTodoIcon className="size-4" />} title={row.title ?? ""}>
                  <p className="text-muted-foreground">{itemCount(rows, row)}</p>
                </Node>
              )}
            </Line>
          ))}
          <Line arrow last>
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
          </Line>
        </div>
      </section>
      <aside
        aria-label="Task details"
        className="min-h-0 space-y-0 overflow-y-auto border-t px-6 py-5 text-sm md:border-t-0 md:border-l"
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

const STRUCK = ["SKIPPED", "SUPERSEDED"];

/** One line of the canvas: the flow node (after an arrow), and what happened beside it. */
function Line({
  arrow,
  last,
  notes = [],
  children,
}: {
  arrow?: boolean;
  last?: boolean;
  notes?: Note[];
  children: ReactNode;
}) {
  return (
    <>
      <div className="flex flex-col items-center">
        {arrow && <Arrow />}
        <div className="flex w-full justify-center">{children}</div>
        {/* the flow continues past a node whose notes make its line taller */}
        {!last && <span aria-hidden className="bg-foreground/40 w-px flex-1" />}
      </div>
      <div>
        {arrow && (
          <div aria-hidden className="invisible max-md:hidden">
            <Arrow />
          </div>
        )}
        {notes.length > 0 && <Notes notes={notes} />}
      </div>
    </>
  );
}

/** Side boxes level with their node, joined to it by one dashed line and a dashed rail. */
function Notes({ notes }: { notes: Note[] }) {
  return (
    <ol
      aria-label="What happened"
      className="before:border-foreground/30 md:border-foreground/30 relative max-w-xs space-y-1.5 py-2 md:border-l md:border-dashed md:py-0 md:pl-3 md:before:absolute md:before:top-5 md:before:right-full md:before:w-10 md:before:border-t md:before:border-dashed"
    >
      {notes.map((n) => (
        <li
          key={n.id}
          className={cn(
            "bg-background rounded-lg border px-3 py-1.5 text-xs",
            n.trigger && "border-primary/40 border-dashed",
          )}
        >
          <p className="flex items-center gap-1.5">
            {n.trigger && <TriggerIcon trigger={n.trigger} className="text-primary size-3.5" />}
            <span className={cn("font-medium", n.trigger && "text-primary")}>{n.label}</span>
            {n.status && !["SUCCEEDED", "completed"].includes(n.status) && (
              <span className="text-muted-foreground">· {statusLabel(n.status)}</span>
            )}
            <time className="text-muted-foreground ml-auto shrink-0 pl-2 tabular-nums">
              {n.at &&
                new Date(n.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </time>
          </p>
          {n.detail && (
            <p className="text-muted-foreground mt-0.5 break-words whitespace-pre-line">
              {n.detail}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function ItemNode({ item }: { item: PlanItem }) {
  const connector = item.tool?.split(".")[0];
  return (
    <div className="bg-card flex w-full items-center gap-2.5 rounded-xl border px-3 py-2 text-sm shadow-xs">
      <StatusIcon status={item.status ?? "PENDING"} className="size-5" />
      <span className="text-muted-foreground text-xs tabular-nums">#{item.ordinal}</span>
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          STRUCK.includes(item.status ?? "") && "text-muted-foreground line-through",
        )}
      >
        {item.title}
      </span>
      {connector && connector !== "harness" && (
        <ConnectorIcon connector={connector} className="size-4" />
      )}
    </div>
  );
}

/** "3 items": the item rows between a round's header and the next header. */
function itemCount(rows: FlowRow[], header: FlowRow) {
  const after = rows.slice(rows.indexOf(header) + 1);
  const next = after.findIndex((r) => !r.item);
  const n = next === -1 ? after.length : next;
  return `${n} item${n === 1 ? "" : "s"}`;
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
      className={`bg-card flex w-full shrink-0 gap-3 rounded-xl border px-4 py-3 text-sm shadow-xs ${narrow ? "max-w-xs" : "max-w-md"}`}
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
    <div aria-hidden className="flex shrink-0 flex-col items-center py-1">
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
