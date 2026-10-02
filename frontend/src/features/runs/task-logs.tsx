import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRightIcon } from "lucide-react";
import { useState } from "react";

import { listRunLogsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { StepOut } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { SearchInput } from "@/components/shared/search-input";
import { cn } from "@/lib/utils";

import { StepDetail } from "./step-detail";
import { previousCall } from "./steps-model";

const LEVELS = ["debug", "info", "warn", "error"] as const;
const LEVEL_TONE: Record<string, string> = {
  debug: "bg-muted text-muted-foreground",
  info: "bg-primary/10 text-primary",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  error: "bg-destructive/10 text-destructive",
};

const ROW = "grid grid-cols-[1rem_6rem_5rem_10rem_1fr] items-center gap-3 px-3 py-2";

/**
 * The task's log lines: text and level filtered by the server, stage on the page. A line
 * opens into its step: what the model was asked and answered, or the tool's input and output.
 */
export function TaskLogs({
  runId,
  taskId,
  steps,
}: {
  runId: string;
  taskId: string;
  steps: StepOut[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState<string>();
  const [level, setLevel] = useState("all");
  const [stage, setStage] = useState("all");
  const logs = useQuery({
    ...listRunLogsOptions({
      path: { run_id: runId },
      query: { task_id: taskId, q, level: level === "all" ? undefined : level },
    }),
    placeholderData: keepPreviousData,
  });
  const rows = logs.data ?? [];
  const stages = [...new Set(rows.map((l) => l.stage))].sort();
  const shown = stage === "all" ? rows : rows.filter((l) => l.stage === stage);
  return (
    <div className="space-y-4 px-6 py-4">
      <div className="flex flex-wrap gap-3">
        <div className="w-80">
          <SearchInput label="Search logs" placeholder="Search logs…" value={q} onCommit={setQ} />
        </div>
        <SimpleSelect
          label="Level"
          className="w-40"
          value={level}
          onChange={setLevel}
          options={[
            { value: "all", label: "All levels" },
            ...LEVELS.map((l) => ({ value: l, label: l })),
          ]}
        />
        <SimpleSelect
          label="Stage"
          className="w-56"
          value={stage}
          onChange={setStage}
          options={[
            { value: "all", label: "All steps" },
            ...stages.map((s) => ({ value: s, label: s })),
          ]}
        />
      </div>
      {shown.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">No log lines.</p>
      ) : (
        <div className="divide-y rounded-xl border text-sm">
          <div className={cn(ROW, "text-muted-foreground font-medium")}>
            <span />
            <span>Time</span>
            <span>Level</span>
            <span>Step</span>
            <span>Message</span>
          </div>
          {shown.map((l) => {
            const step = steps.find((st) => st.id === l.step_id);
            const isOpen = open === l.id;
            const cells = (
              <>
                {step ? (
                  <ChevronRightIcon
                    className={cn("text-muted-foreground size-4 transition", isOpen && "rotate-90")}
                  />
                ) : (
                  <span />
                )}
                <span className="tabular-nums">
                  {new Date(l.at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
                <span>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[0.65rem] font-semibold tracking-wide uppercase",
                      LEVEL_TONE[l.level] ?? LEVEL_TONE.debug,
                    )}
                  >
                    {l.level}
                  </span>
                </span>
                <span className="truncate">{l.stage}</span>
                <span>{l.message}</span>
              </>
            );
            return (
              <div key={l.id}>
                {step ? (
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => setOpen(isOpen ? null : l.id)}
                    className={cn(ROW, "hover:bg-muted/50 w-full text-left")}
                  >
                    {cells}
                  </button>
                ) : (
                  <div className={ROW}>{cells}</div>
                )}
                {isOpen && step && (
                  <div className="bg-muted/20 border-t px-6 py-4">
                    <StepDetail runId={runId} step={step} previous={previousCall(step, steps)} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
