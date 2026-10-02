import { useQuery } from "@tanstack/react-query";

import { getRunOptions } from "@/api/generated/@tanstack/react-query.gen";
import { QueryState } from "@/components/shared/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SubjectDrawer } from "@/features/subjects/subject-drawer";

import { pollEvery } from "./model";
import { RunHeader } from "./run-header";
import { RunTabs } from "./run-tabs";
import { TaskDrawer } from "./task-drawer";

export type RunTab = "tasks" | "episodes" | "journal" | "attention";

/** One run: header and controls, then its tasks, episodes, journal and attention. */
export function RunDetail({
  runId,
  tab,
  taskId,
  subjectOpen,
  onTab,
  onTask,
  onSubject,
}: {
  runId: string;
  tab: RunTab;
  taskId?: string;
  subjectOpen: boolean;
  onTab: (tab: RunTab) => void;
  onTask: (taskId: string | undefined) => void;
  onSubject: (open: boolean) => void;
}) {
  const run = useQuery({
    ...getRunOptions({ path: { run_id: runId } }),
    refetchInterval: (q) => pollEvery(q.state.data?.status),
  });
  return (
    <QueryState query={run} what="This run" loading={<Skeleton className="h-96 w-full" />}>
      {(r) => (
        <>
          <RunHeader run={r} onSubject={() => onSubject(true)} />
          <Tabs value={tab} onValueChange={(t) => onTab(t as RunTab)}>
            <TabsList variant="line" className="mb-6">
              <TabsTrigger value="tasks">Tasks</TabsTrigger>
              <TabsTrigger value="episodes">Episodes</TabsTrigger>
              <TabsTrigger value="journal">Journal</TabsTrigger>
              <TabsTrigger value="attention">Attention</TabsTrigger>
            </TabsList>
            <RunTabs run={r} onTask={onTask} />
          </Tabs>
          {taskId && (
            <TaskDrawer run={r} taskId={taskId} onTask={onTask} onClose={() => onTask(undefined)} />
          )}
          {subjectOpen && (
            <SubjectDrawer
              firmId={r.firm_id}
              subjectId={r.subject_id}
              readOnly
              onClose={() => onSubject(false)}
            />
          )}
        </>
      )}
    </QueryState>
  );
}
