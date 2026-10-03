import { useQuery } from "@tanstack/react-query";
import { LinkIcon } from "lucide-react";

import {
  listRunAttentionOptions,
  listRunEpisodesOptions,
  listRunJournalOptions,
  listRunTasksOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type {
  EpisodeOut,
  JournalOut,
  RunOut,
  StepResultOut,
  TaskOut,
} from "@/api/generated/types.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { QueryState } from "@/components/shared/query-state";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { TabsContent } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { dateTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { AttentionCard } from "./attention-card";
import { KANBAN, duration, itemProgress, pollEvery, statusLabel, taskTarget } from "./model";
import { StatusIcon, StatusPill, TriggerIcon } from "./status-pill";

/** The run's four views, each polling while the run can still change. */
export function RunTabs({ run, onTask }: { run: RunOut; onTask: (taskId: string) => void }) {
  const poll = pollEvery(run.status);
  const path = { path: { run_id: run.id } };
  const tasks = useQuery({ ...listRunTasksOptions(path), refetchInterval: poll });
  const episodes = useQuery({ ...listRunEpisodesOptions(path), refetchInterval: poll });
  const journal = useQuery({ ...listRunJournalOptions(path), refetchInterval: poll });
  const attention = useQuery({ ...listRunAttentionOptions(path), refetchInterval: poll });
  return (
    <>
      <TabsContent value="tasks">
        <QueryState query={tasks} what="Tasks">
          {(t) => <TasksBoard tasks={t} onOpen={onTask} />}
        </QueryState>
      </TabsContent>
      <TabsContent value="episodes">
        <QueryState
          query={episodes}
          what="Episodes"
          isEmpty={(e) => e.length === 0}
          empty={<EmptyState title="No episodes yet" />}
        >
          {(e) => <EpisodesTimeline episodes={e} tasks={tasks.data ?? []} onTask={onTask} />}
        </QueryState>
      </TabsContent>
      <TabsContent value="journal">
        <QueryState query={journal} what="Journal">
          {(j) => <JournalView journal={j} />}
        </QueryState>
      </TabsContent>
      <TabsContent value="attention">
        <QueryState
          query={attention}
          what="Attention"
          isEmpty={(a) => a.length === 0}
          empty={<EmptyState title="Nothing needs a person" />}
        >
          {(a) => <AttentionList items={a} />}
        </QueryState>
      </TabsContent>
    </>
  );
}

/** Six fixed-width columns side by side, scrolling sideways; each card opens its task. */
export function TasksBoard({ tasks, onOpen }: { tasks: TaskOut[]; onOpen: (id: string) => void }) {
  const finished = new Set(
    tasks.filter((t) => ["DONE", "SKIPPED", "FAILED"].includes(t.status)).map((t) => t.key),
  );
  return (
    <div className="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-3">
      {KANBAN.map((col) => {
        const items = tasks.filter((t) => (col.statuses as readonly string[]).includes(t.status));
        return (
          <section
            key={col.key}
            aria-label={`${col.label} (${items.length})`}
            className="bg-muted/40 flex max-h-[70vh] min-h-[60vh] min-w-44 flex-1 snap-start flex-col rounded-xl"
          >
            <h3 className="flex items-center gap-2 px-3 pt-3 pb-2 text-sm font-medium">
              <span aria-hidden>
                <StatusIcon status={col.statuses[0]} className="size-5" />
              </span>
              {col.label}
              <span className="bg-background text-muted-foreground ml-auto rounded-full px-2 text-xs tabular-nums">
                {items.length}
              </span>
            </h3>
            <ul className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
              {items.map((t) => {
                const { done, total } = itemProgress(t.plan as { status?: string }[]);
                const waitingOn = t.depends_on.filter((k) => !finished.has(k));
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => onOpen(t.id)}
                      className={cn(
                        "bg-card hover:border-foreground/25 focus-visible:ring-ring w-full space-y-2.5 rounded-lg border p-3 text-left text-sm shadow-xs transition hover:shadow-md focus-visible:ring-2 focus-visible:outline-none",
                        t.status === "FAILED" && "border-destructive/50",
                      )}
                    >
                      <div className="flex items-start gap-1.5">
                        <p className="flex-1 leading-snug font-medium">{t.title}</p>
                        {waitingOn.length > 0 && (
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <span
                                  aria-label={`Waiting on ${waitingOn.join(", ")}`}
                                  className="text-muted-foreground"
                                />
                              }
                            >
                              <LinkIcon className="size-3.5" />
                            </TooltipTrigger>
                            <TooltipContent>Waiting on {waitingOn.join(", ")}</TooltipContent>
                          </Tooltip>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 text-xs">
                        <Badge variant="secondary" className="capitalize">
                          {t.kind.replaceAll("_", " ")}
                        </Badge>
                        <span className="text-muted-foreground truncate">{taskTarget(t.key)}</span>
                      </div>
                      {total > 0 && (
                        <div className="space-y-1">
                          <Progress value={(done / total) * 100} className="h-1" />
                          <p className="text-muted-foreground flex justify-between text-xs tabular-nums">
                            <span>
                              {done}/{total} items
                            </span>
                            <span>{duration(t.started_at, t.ended_at)}</span>
                          </p>
                        </div>
                      )}
                      {t.status === "FAILED" && <p className="text-destructive text-xs">Failed</p>}
                    </button>
                  </li>
                );
              })}
              {items.length === 0 && (
                <li className="text-muted-foreground/70 rounded-lg border border-dashed py-8 text-center text-xs">
                  No tasks
                </li>
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function EpisodesTimeline({
  episodes,
  tasks,
  onTask,
}: {
  episodes: EpisodeOut[];
  tasks: TaskOut[];
  onTask: (id: string) => void;
}) {
  const newest = [...episodes].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <ol aria-label="Episodes" className="relative ml-3 space-y-3 border-l pl-6">
      {newest.map((e) => {
        const taskTitle = tasks.find((t) => t.id === e.task_id)?.title;
        return (
          <li key={e.id} className="relative">
            <span className="bg-background absolute top-0.5 -left-[2.1rem] flex size-6 items-center justify-center rounded-full border">
              <TriggerIcon trigger={e.trigger_type} className="text-muted-foreground size-3.5" />
            </span>
            <div className="bg-card space-y-1 rounded-lg border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">
                  {statusLabel(e.trigger_type)}
                  {e.source && ` · ${e.source}`}
                </p>
                <StatusPill status={e.status.toUpperCase()} />
                {e.outcome && <Badge variant="secondary">{e.outcome}</Badge>}
              </div>
              <p className="text-muted-foreground text-xs">
                {e.status === "scheduled" || e.status === "armed"
                  ? `due ${dateTime(e.due_at)} (${relativeTime(e.due_at)})`
                  : `${dateTime(e.started_at ?? e.created_at)}${e.ended_at ? ` → ${dateTime(e.ended_at)}` : ""}`}
              </p>
              {e.reason && <p className="text-muted-foreground text-xs">{e.reason}</p>}
              {e.task_id && taskTitle && (
                <button
                  type="button"
                  className="text-primary text-xs hover:underline"
                  onClick={() => onTask(e.task_id!)}
                >
                  {taskTitle}
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const SOURCE_TONE: Record<string, string> = {
  harness: "bg-muted text-muted-foreground",
  agent: "bg-primary/10 text-primary",
  human: "bg-brass/15 text-brass",
};

export function JournalView({ journal }: { journal: JournalOut }) {
  if (!journal.summary && journal.entries.length === 0)
    return <EmptyState title="Nothing in the journal yet" />;
  return (
    <div className="space-y-3">
      {journal.summary && (
        <div className="bg-card rounded-lg border p-3 text-sm">
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Summary so far
          </p>
          <p>{journal.summary}</p>
        </div>
      )}
      <ul className="divide-y rounded-lg border">
        {journal.entries.map((j) => (
          <li key={j.id} className="flex gap-3 px-3 py-2 text-sm">
            <span
              className={cn(
                "h-5 shrink-0 rounded-full px-2 text-xs leading-5",
                SOURCE_TONE[j.source] ?? SOURCE_TONE.harness,
              )}
            >
              {j.source}
            </span>
            <span className="flex-1">{j.text}</span>
            <span className="text-muted-foreground shrink-0 text-xs">
              {relativeTime(j.created_at)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AttentionList({ items }: { items: StepResultOut[] }) {
  const sorted = [...items].sort(
    (a, b) => Number(b.status === "open") - Number(a.status === "open"),
  );
  return (
    <ul className="space-y-2">
      {sorted.map((a) => (
        <li key={a.id}>
          <AttentionCard item={a} />
        </li>
      ))}
    </ul>
  );
}
