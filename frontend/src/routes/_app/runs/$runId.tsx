import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { RunDetail } from "@/features/runs/run-detail";

export const RUN_TABS = ["tasks", "episodes", "journal", "attention"] as const;

export const Route = createFileRoute("/_app/runs/$runId")({
  validateSearch: z.object({
    tab: z.enum(RUN_TABS).catch("tasks").default("tasks"),
    /** The open task drawer. */
    task: z.string().optional().catch(undefined),
    /** The subject drawer is open. */
    subject: z.boolean().optional().catch(undefined),
  }),
  component: function Run() {
    const { runId } = Route.useParams();
    const { tab, task, subject } = Route.useSearch();
    const navigate = Route.useNavigate();
    const patch = (p: { tab?: (typeof RUN_TABS)[number]; task?: string; subject?: boolean }) =>
      void navigate({ search: (prev) => ({ ...prev, ...p }) });
    return (
      <RunDetail
        key={runId}
        runId={runId}
        tab={tab}
        taskId={task}
        subjectOpen={!!subject}
        onTab={(t) => patch({ tab: t })}
        onTask={(t) => patch({ task: t })}
        onSubject={(open) => patch({ subject: open || undefined })}
      />
    );
  },
});
