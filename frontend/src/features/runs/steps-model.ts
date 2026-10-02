import type { EpisodeOut, StepOut, TaskOut } from "@/api/generated/types.gen";

/** A plan item as stored in `run_tasks.plan` (DATA_MODEL §4.3); every field may be missing. */
export type PlanItem = {
  id: string;
  ordinal?: number;
  title?: string;
  kind?: string;
  tool?: string | null;
  input_hint?: string;
  status?: string;
  reason?: string | null;
  superseded_by?: string[];
  attempts?: number;
  output?: { summary?: string; data?: Record<string, unknown> } | null;
  started_at?: string | null;
  ended_at?: string | null;
};

const ACTIONS = ["tool", "subagent", "policy", "guardrail"];

/** The actions taken for an item (each try of a tool, a block, the subagent), oldest first. */
export const attemptsFor = (item: PlanItem, steps: StepOut[]) =>
  steps
    .filter((s) => s.plan_item_id === item.id && ACTIONS.includes(s.kind) && !s.parent_step_id)
    .sort((a, b) => a.seq - b.seq);

/** A subagent's model calls, one round per plan → write → review (a replan starts another). */
export function subagentRounds(parent: StepOut, steps: StepOut[]) {
  const children = steps
    .filter((s) => s.parent_step_id === parent.id)
    .sort((a, b) => a.seq - b.seq);
  const rounds: StepOut[][] = [];
  for (const c of children) {
    if (c.role === "sub_planner" || rounds.length === 0) rounds.push([]);
    rounds[rounds.length - 1].push(c);
  }
  return rounds;
}

export const replacedBy = (item: PlanItem, plan: PlanItem[]) =>
  plan.filter((i) => item.superseded_by?.includes(i.id));

export function attemptLabel(s: StepOut, index: number) {
  const what =
    (s.output?.ended_reason as string | undefined) ??
    s.summary ??
    s.status.charAt(0) + s.status.slice(1).toLowerCase().replaceAll("_", " ");
  return `Attempt ${index + 1} · ${what}`;
}

/** The arguments worth showing at a glance: short scalar values, `key=value`. */
export const keyArgs = (input: Record<string, unknown>) =>
  Object.entries(input)
    .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v) && String(v).length <= 60)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(", ");

/** The connectors a task's plan uses (harness tools aren't connectors), with call counts. */
export function connectorsOf(task: TaskOut, steps: StepOut[]) {
  const names = new Set(
    (task.plan as PlanItem[])
      .map((i) => i.tool?.split(".")[0])
      .filter((c): c is string => !!c && c !== "harness"),
  );
  return [...names].map((name) => ({
    name,
    calls: steps.filter((s) => s.kind === "tool" && s.tool?.startsWith(`${name}.`)).length,
  }));
}

/** The episode that brought the task in: the last run-wide one at or before its creation. */
export function triggerOf(task: TaskOut, episodes: EpisodeOut[]) {
  return [...episodes]
    .filter((e) => !e.task_id && e.created_at <= task.created_at)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

const ROLES: Record<string, string> = {
  triage: "Triage",
  planner: "Planner",
  executor: "Executor · fills the tool's arguments",
  relevance: "Relevance check",
  guardrail: "Guardrail",
  sub_planner: "Subagent · planner",
  sub_executor: "Subagent · writer",
  sub_reviewer: "Subagent · reviewer",
  summarizer: "Summarizer",
  completion: "Completion check",
  completion_judge: "Completion judge",
};

/** What a model call was for, in words (`sub_reviewer` → "Subagent · reviewer"). */
export const roleLabel = (role?: string | null) =>
  role ? (ROLES[role] ?? role.replaceAll("_", " ")) : "Model call";

export type Turn = { speaker: "agent" | "contact"; text: string };

/** Vapi's transcript ("AI: …\nUser: …") as turns; a line without a speaker continues the last. */
export function transcriptTurns(transcript: string): Turn[] {
  const turns: Turn[] = [];
  for (const line of transcript.split("\n")) {
    const m = /^(AI|Assistant|Bot|User|Customer):\s*(.*)$/i.exec(line.trim());
    if (m)
      turns.push({ speaker: /^(user|customer)$/i.test(m[1]) ? "contact" : "agent", text: m[2] });
    else if (line.trim() && turns.length) turns[turns.length - 1].text += ` ${line.trim()}`;
    else if (line.trim()) turns.push({ speaker: "agent", text: line.trim() });
  }
  return turns;
}
