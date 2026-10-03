import { Dialog as SheetPrimitive } from "@base-ui/react/dialog";
import { useQuery } from "@tanstack/react-query";
import { ListTodoIcon, XIcon } from "lucide-react";
import { useState } from "react";

import {
  listRunEpisodesOptions,
  listRunStepsOptions,
  listRunTasksOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { RunOut, StepOut, TaskOut } from "@/api/generated/types.gen";
import { MoreButton } from "@/components/shared/more-button";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { dateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { duration, pollEvery, statusLabel } from "./model";
import { StatusIcon, StatusPill } from "./status-pill";
import { TaskIO, type IOSection } from "./task-io";
import { TaskLogs } from "./task-logs";
import { TaskOverview } from "./task-overview";
import { TaskSteps } from "./task-steps";

type DrawerTab = "overview" | "steps" | "logs" | "io";

/**
 * Everything about one task of a run, in a large floating panel (docs/ui-refs): how it ran,
 * its plan items and their attempts, its logs, and its inputs and outputs. The Run toggle
 * shows the run's own steps (triage, completion checks).
 */
export function TaskDrawer({
  run,
  taskId,
  onTask,
  onClose,
}: {
  run: RunOut;
  taskId: string;
  onTask: (taskId: string) => void;
  onClose: () => void;
}) {
  const poll = pollEvery(run.status);
  const tasks = useQuery({
    ...listRunTasksOptions({ path: { run_id: run.id } }),
    refetchInterval: poll,
  });
  const [view, setView] = useState<"task" | "run">("task");
  return (
    <SheetPrimitive.Root open onOpenChange={(open) => open || onClose()}>
      <SheetPrimitive.Portal>
        <SheetPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/10 transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-sm" />
        <SheetPrimitive.Popup className="bg-background fixed inset-y-3 right-3 z-50 flex w-[min(1240px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border shadow-2xl transition duration-200 data-ending-style:translate-x-6 data-ending-style:opacity-0 data-starting-style:translate-x-6 data-starting-style:opacity-0 md:inset-y-6 md:right-6 md:w-[min(1240px,calc(100vw-3rem))]">
          <QueryState query={tasks} what="Tasks" loading={<Skeleton className="m-6 h-96" />}>
            {(all) => {
              const t = all.find((x) => x.id === taskId) ?? all[0];
              return (
                <>
                  <div className="flex items-center gap-3 border-b px-6 py-2.5">
                    <ToggleGroup
                      value={[view]}
                      onValueChange={(v) => v[0] && setView(v[0] as "task" | "run")}
                      aria-label="Show"
                      variant="outline"
                      size="sm"
                    >
                      <ToggleGroupItem value="task">Task</ToggleGroupItem>
                      <ToggleGroupItem value="run">Run</ToggleGroupItem>
                    </ToggleGroup>
                    {view === "task" && t && (
                      <TaskSelect tasks={all} value={t.id} onChange={onTask} />
                    )}
                    <SheetPrimitive.Close
                      render={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="ml-auto"
                          aria-label="Close"
                        />
                      }
                    >
                      <XIcon />
                    </SheetPrimitive.Close>
                  </div>
                  {view === "run" ? (
                    <RunSteps run={run} />
                  ) : t ? (
                    <TaskPanel key={t.id} run={run} task={t} />
                  ) : (
                    <p className="text-muted-foreground p-6 text-sm">This run has no tasks yet.</p>
                  )}
                </>
              );
            }}
          </QueryState>
        </SheetPrimitive.Popup>
      </SheetPrimitive.Portal>
    </SheetPrimitive.Root>
  );
}

function TaskSelect({
  tasks,
  value,
  onChange,
}: {
  tasks: TaskOut[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => v && onChange(v as string)}
      items={tasks.map((t) => ({ value: t.id, label: t.title }))}
    >
      <SelectTrigger aria-label="Task" className="h-8 w-72">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {tasks.map((t) => (
          <SelectItem key={t.id} value={t.id}>
            <StatusIcon status={t.status} className="size-4" />
            {t.title}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function TaskPanel({ run, task }: { run: RunOut; task: TaskOut }) {
  const poll = pollEvery(run.status);
  const [tab, setTab] = useState<DrawerTab>("overview");
  const [section, setSection] = useState<IOSection>("user");
  const steps = useQuery({
    ...listRunStepsOptions({ path: { run_id: run.id }, query: { task_id: task.id } }),
    refetchInterval: poll,
  });
  const episodes = useQuery({
    ...listRunEpisodesOptions({ path: { run_id: run.id } }),
    refetchInterval: poll,
  });
  const itemCount = task.plan.filter(
    (i) => (i as { status?: string }).status !== "SUPERSEDED",
  ).length;
  const all: StepOut[] = steps.data ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-start gap-3 px-6 pt-5">
        <span className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-xl">
          <ListTodoIcon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-lg font-semibold">{task.title}</h2>
          <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
            <StatusPill status={task.status} />
            <span>{dateTime(task.started_at ?? task.created_at)}</span>
            <span aria-hidden>•</span>
            <span>{duration(task.started_at, task.ended_at)}</span>
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger render={<MoreButton label={`Actions for ${task.title}`} />} />
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => void navigator.clipboard?.writeText(task.key)}>
              Copy task key
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => void navigator.clipboard?.writeText(run.id)}>
              Copy run ID
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>
      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as DrawerTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList variant="line" className="mx-6 mt-3">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="steps">Steps ({itemCount})</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          <TabsTrigger value="io">Inputs & Outputs</TabsTrigger>
        </TabsList>
        <div className="min-h-0 flex-1 overflow-y-auto border-t">
          <TabsContent value="overview" className="h-full">
            <TaskOverview
              run={run}
              task={task}
              steps={all}
              episodes={episodes.data ?? []}
              onViewOutput={() => {
                setSection("final");
                setTab("io");
              }}
            />
          </TabsContent>
          <TabsContent value="steps" className="h-full">
            <TaskSteps runId={run.id} task={task} steps={all} />
          </TabsContent>
          <TabsContent value="logs">
            <TaskLogs runId={run.id} taskId={task.id} steps={all} />
          </TabsContent>
          <TabsContent value="io" className="h-full">
            <TaskIO
              runId={run.id}
              task={task}
              steps={all}
              episodes={episodes.data ?? []}
              section={section}
              onSection={setSection}
            />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

/** The run's own steps: triage of each message, completion checks. */
function RunSteps({ run }: { run: RunOut }) {
  const steps = useQuery({
    ...listRunStepsOptions({ path: { run_id: run.id } }),
    refetchInterval: pollEvery(run.status),
  });
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-6">
      <h2 className="mb-1 text-lg font-semibold">
        @{run.agent_handle} on {run.subject_title}
      </h2>
      <p className="text-muted-foreground mb-4 text-sm">
        The run's own work: reading each message (triage) and checking whether the goal is met.
      </p>
      <QueryState query={steps} what="Steps">
        {(all) => {
          const own = all.filter((s) => !s.task_id);
          return own.length === 0 ? (
            <p className="text-muted-foreground text-sm">Nothing yet.</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {own.map((s) => (
                <li key={s.id} className="flex items-start gap-3 px-4 py-3 text-sm">
                  <StatusIcon status={s.status} />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{s.role ?? s.tool ?? statusLabel(s.kind)}</p>
                    {s.summary && <p className="text-muted-foreground">{s.summary}</p>}
                  </div>
                  <span className={cn("text-muted-foreground shrink-0 text-xs")}>
                    {dateTime(s.started_at)} · {duration(s.started_at, s.ended_at)}
                    {s.model && ` · ${s.model}`}
                  </span>
                </li>
              ))}
            </ul>
          );
        }}
      </QueryState>
    </div>
  );
}
