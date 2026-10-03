import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon, HandIcon, Undo2Icon } from "lucide-react";
import { useState } from "react";

import { listRunAttentionOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { RunOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { dateTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { AttentionCard } from "./attention-card";
import { ControlDialog } from "./control-dialog";
import { canHandBack, canTakeOver, pollEvery } from "./model";
import { StatusPill } from "./status-pill";

/** Who is working on what, toward which goal, and the human controls over it. */
export function RunHeader({ run, onSubject }: { run: RunOut; onSubject: () => void }) {
  const [control, setControl] = useState<"takeover" | "handback" | null>(null);
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const attention = useQuery({
    ...listRunAttentionOptions({ path: { run_id: run.id } }),
    enabled: run.status === "AWAITING_CONFIRMATION",
    refetchInterval: pollEvery(run.status),
  });
  const confirm = attention.data?.find(
    (a) => a.kind === "confirm_completion" && a.status === "open",
  );
  const takeover = run.takeover as { remarks?: string; at?: string } | null;
  return (
    <header className="mb-6 space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1 space-y-1.5">
          <h1 className="text-[1.375rem] leading-tight font-semibold tracking-tight">
            @{run.agent_handle} on{" "}
            <button type="button" onClick={onSubject} className="hover:underline">
              {run.subject_title}
            </button>
          </h1>
          <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
            <StatusPill status={run.status} />
            {run.substatus && <span className="text-xs">{run.substatus}</span>}
            <span>·</span>
            <span>started {dateTime(run.started_at)}</span>
            {run.cycle > 0 && <span>· cycle {run.cycle}</span>}
            <span className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">v{run.version}</span>
            {run.next_wake_at && <span>· next wake-up {relativeTime(run.next_wake_at)}</span>}
            {run.ended_reason && <span>· ended: {run.ended_reason}</span>}
          </div>
        </div>
        <div className="flex gap-2">
          {canTakeOver(run) && (
            <Button variant="outline" onClick={() => setControl("takeover")}>
              <HandIcon /> Take over
            </Button>
          )}
          {canHandBack(run) && (
            <Button onClick={() => setControl("handback")}>
              <Undo2Icon /> Hand back
            </Button>
          )}
        </div>
      </div>
      {run.status === "TAKEN_OVER" && takeover && (
        <div className="bg-brass/10 border-brass/30 rounded-lg border px-4 py-3 text-sm">
          <p className="font-medium">Taken over {relativeTime(takeover.at)}</p>
          <p className="text-muted-foreground">{takeover.remarks}</p>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <div className="bg-card rounded-lg border p-3 text-sm">
          <p className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
            Goal
          </p>
          <p>{run.goal || "Set by the agent when it starts"}</p>
        </div>
        <div className="bg-card rounded-lg border p-3 text-sm">
          <button
            type="button"
            className="text-muted-foreground mb-1 flex w-full items-center gap-1 text-xs font-medium tracking-wide uppercase"
            onClick={() => setCriteriaOpen((o) => !o)}
            aria-expanded={criteriaOpen}
          >
            Done when
            <ChevronDownIcon className={cn("size-3.5 transition", criteriaOpen && "rotate-180")} />
          </button>
          <p className={cn(!criteriaOpen && "line-clamp-2")}>
            {run.completion_criteria || "Set by the agent when it starts"}
          </p>
        </div>
      </div>
      {confirm && <AttentionCard item={confirm} />}
      {control && (
        <ControlDialog action={control} runId={run.id} onClose={() => setControl(null)} />
      )}
    </header>
  );
}
