/** The runtime's vocabulary, shared by the runs pages, the task drawer and the playground. */

export const TERMINAL_RUN = ["COMPLETED", "ENDED"] as const;
export const isTerminal = (status: string) => (TERMINAL_RUN as readonly string[]).includes(status);

/** The tasks board: each column lists the task statuses it holds. */
export const KANBAN = [
  { key: "todo", label: "Todo", statuses: ["TODO"] },
  { key: "progress", label: "In progress", statuses: ["IN_PROGRESS"] },
  { key: "waiting", label: "Waiting", statuses: ["WAITING"] },
  { key: "blocked", label: "Blocked", statuses: ["BLOCKED"] },
  { key: "done", label: "Done", statuses: ["DONE"] },
  { key: "skipped", label: "Skipped", statuses: ["SKIPPED", "FAILED"] },
] as const;

type Item = { status?: string };

/** Items done out of items that count: a superseded item was replaced, so it doesn't. */
export function itemProgress(plan: readonly Item[]) {
  const counted = plan.filter((i) => i.status !== "SUPERSEDED");
  return {
    done: counted.filter((i) => i.status === "DONE" || i.status === "SKIPPED").length,
    total: counted.length,
  };
}

export function duration(start?: string | null, end?: string | null, now = Date.now()) {
  if (!start) return "—";
  const s = Math.max(0, Math.round(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  return m ? `${m}m ${s % 60}s` : `${s}s`;
}

/** What a task acts on, from its key (`call-client:contact-536639ae` → `contact-536639ae`). */
export const taskTarget = (key: string) => {
  const target = key.slice(key.indexOf(":") + 1);
  return target === "run" ? "whole run" : target;
};

/** What the orchestrator is doing while a message is being handled (`progress` events). */
export const PROGRESS_STAGES: Record<string, string> = {
  subject: "Finding the case…",
  scoring: "Checking the agent can do this…",
  brief: "Writing the brief…",
};

/** Run views refresh every 3s while the run can still change. */
export const pollEvery = (status: string | undefined): number | false =>
  status && !isTerminal(status) ? 3000 : false;

type RunState = { status: string; substatus?: string | null };

/** Take over: live runs, and a run paused by repeated failures (hand back resumes it). */
export const canTakeOver = ({ status, substatus }: RunState) =>
  ["CREATED", "ACTIVE", "AWAITING_CONFIRMATION"].includes(status) ||
  (status === "PAUSED" && substatus === "repeated_failure");

export const canHandBack = ({ status }: { status: string }) => status === "TAKEN_OVER";

/** `AWAITING_CONFIRMATION` → "Awaiting confirmation". */
export const statusLabel = (status: string) =>
  status.charAt(0).toUpperCase() + status.slice(1).toLowerCase().replaceAll("_", " ");

export const RUN_STATUSES = [
  "ACTIVE",
  "AWAITING_CONFIRMATION",
  "TAKEN_OVER",
  "PAUSED",
  "COMPLETED",
  "ENDED",
] as const;
