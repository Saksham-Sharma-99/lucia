import type { EpisodeOut, StepOut, TaskOut } from "@/api/generated/types.gen";

import { statusLabel } from "./model";

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
  added_in?: number;
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

/** Something that happened, shown beside the node it concerns. */
export type Note = {
  id: string;
  at: string;
  label: string;
  detail?: string | null;
  status?: string;
  trigger?: string;
};
/** One node of the downstream flow: a round's header (Plan, Added) or one of its items. */
export type FlowRow = { key: string; title?: string; item?: PlanItem; notes: Note[] };
type Entry = {
  id: string;
  task_id: string | null;
  episode_id: string | null;
  text: string;
  created_at: string;
};

const STEP_EVENT: Record<string, string> = {
  "vapi.place_call": "Call placed",
  "harness.emit_finding": "Finding reported",
  "harness.ask_human": "Asked a person",
  subagent: "Subagent wrote a draft",
  policy: "Policy check",
  guardrail: "Guardrail check",
};

/** When an episode reached the run: a scheduled one is created early and fires at `due_at`. */
const arrived = (e: EpisodeOut) => e.started_at ?? e.due_at ?? e.created_at;

/** What a step recorded, as a note's description: plan items, verdicts, a call's summary… */
function stepDetail(s: StepOut, label: string): string | null {
  const out = s.output ?? {};
  const items = out.items as { title?: string }[] | undefined;
  if (s.role === "planner" && items)
    return [`${items.length} items:`, ...items.map((it, i) => `${i + 1}. ${it.title}`)].join("\n");
  const verdicts = out.verdicts as
    { item_id: string; verdict: string; reason: string }[] | undefined;
  if (verdicts) return verdicts.map((v) => `#${v.item_id} ${v.verdict}: ${v.reason}`).join("\n");
  const said =
    (out.summary as string | undefined) ??
    (out.text as string | undefined) ??
    (s.input?.summary as string | undefined) ??
    (out.ended_reason as string | undefined)?.replaceAll("-", " ") ??
    s.summary;
  return said && said !== label ? said : null;
}

/** A step as a note, or null for internal calls (executor, guardrail model, summaries). */
function stepNote(s: StepOut, firstPlanner?: string): Note | null {
  const note = { id: s.id, at: s.started_at ?? "", status: s.status };
  if (s.kind === "llm") {
    const label =
      s.role === "planner"
        ? s.id === firstPlanner
          ? "Plan written"
          : "Plan revised"
        : s.role === "relevance"
          ? "Checked what's still needed"
          : null;
    return label ? { ...note, label, detail: stepDetail(s, label) } : null;
  }
  if (s.parent_step_id || s.tool === "harness.journal_append") return null; // its entry shows
  const label = STEP_EVENT[s.kind] ?? STEP_EVENT[s.tool ?? ""] ?? s.tool ?? statusLabel(s.kind);
  return { ...note, label, detail: stepDetail(s, label) };
}

/**
 * The task as a downstream flow: each plan round (the first plan, then each append, by
 * `added_in`) as a header followed by its items. What happened sits beside the node it
 * concerns: plan writes beside their round; an episode beside the round it appended, else the
 * item running when it arrived (else the next one due); step events beside their item; a
 * relevance check where its episode is; journal entries beside the item running then.
 */
export function flowRows(
  task: TaskOut,
  steps: StepOut[],
  episodes: EpisodeOut[],
  journal: Entry[] = [],
): FlowRow[] {
  const plan = [...(task.plan as PlanItem[])].sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0));
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const rounds = [...new Set(plan.map((i) => i.added_in ?? 0))].sort((a, b) => a - b);
  const rows: FlowRow[] = [];
  for (const n of rounds) {
    rows.push({ key: `round-${n}`, title: n === 0 ? "Plan" : "Added", notes: [] });
    for (const item of plan.filter((i) => (i.added_in ?? 0) === n))
      rows.push({ key: item.id, item, notes: [] });
  }
  const headers = rows.filter((r) => r.title);
  // Consecutive planner calls are one round's plan (a write and its validation retries):
  // burst 0 is the first plan, burst k the k-th append.
  const burstHeader = new Map<string, FlowRow>();
  const burstStart: string[] = [];
  let burst = -1;
  ordered.forEach((s, i) => {
    if (s.role !== "planner") return;
    if (ordered[i - 1]?.role !== "planner") burstStart[++burst] = s.started_at ?? "";
    burstHeader.set(s.id, headers[Math.min(burst, headers.length - 1)]);
  });
  // An append's episode: the task's latest one to arrive before that round was planned.
  const taskEpisodes = episodes
    .filter((e) => e.task_id === task.id)
    .sort((a, b) => arrived(a).localeCompare(arrived(b)));
  const appendedBy = new Map<string, FlowRow>();
  headers.slice(1).forEach((header, k) => {
    const start = burstStart[k + 1];
    const cause = start ? taskEpisodes.findLast((e) => arrived(e) <= start) : undefined;
    if (cause && !appendedBy.has(cause.id)) appendedBy.set(cause.id, header);
  });
  const span = (item: PlanItem) => {
    const tries = ordered.filter((s) => s.plan_item_id === item.id && s.kind !== "llm");
    const last = tries.at(-1);
    if (!last) return null;
    // still open only while its last try is: some finished steps don't record an end time
    const open = ["PENDING", "RUNNING", "AWAITING_CALLBACK"].includes(last.status);
    return {
      start: tries[0].started_at ?? "",
      end: last.ended_at ?? (open ? null : last.started_at),
    };
  };
  const runningAt = (t: string) => {
    const items = rows.filter(
      (r) => r.item && !["SKIPPED", "SUPERSEDED"].includes(r.item.status ?? ""),
    );
    return (
      items.findLast((r) => {
        const sp = span(r.item!);
        return sp && sp.start <= t && (!sp.end || sp.end >= t);
      }) ??
      items.find((r) => {
        const sp = span(r.item!);
        return !sp || sp.start > t;
      }) ??
      rows.at(-1)
    );
  };

  const episodeRow = new Map<string, FlowRow | undefined>();
  for (const e of taskEpisodes) {
    const row = appendedBy.get(e.id) ?? runningAt(arrived(e));
    episodeRow.set(e.id, row);
    row?.notes.push({
      id: e.id,
      at: arrived(e),
      label: ["scheduled", "armed"].includes(e.status) ? "Wake-up scheduled" : "Episode arrived",
      detail: e.reason ?? statusLabel(e.trigger_type),
      trigger: e.trigger_type,
    });
  }
  const firstPlanner = ordered.find((s) => s.role === "planner")?.id;
  for (const s of ordered) {
    const note = stepNote(s, firstPlanner);
    if (!note) continue;
    const row =
      s.role === "planner"
        ? burstHeader.get(s.id)
        : (rows.find((r) => r.item?.id === s.plan_item_id) ??
          (s.episode_id ? episodeRow.get(s.episode_id) : undefined) ??
          runningAt(note.at));
    row?.notes.push(note);
  }
  for (const j of journal.filter((j) => j.task_id === task.id))
    runningAt(j.created_at)?.notes.push({
      id: j.id,
      at: j.created_at,
      label: "Journal entry created",
      detail: j.text,
    });
  for (const r of rows) r.notes.sort((a, b) => a.at.localeCompare(b.at));
  return rows;
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

/** The latest earlier model call of the same role in the same task: what a call is compared to. */
export const previousCall = (call: StepOut, steps: StepOut[]) =>
  call.kind === "llm"
    ? steps
        .filter(
          (s) =>
            s.kind === "llm" &&
            s.role === call.role &&
            s.task_id === call.task_id &&
            s.seq < call.seq,
        )
        .sort((a, b) => b.seq - a.seq)[0]
    : undefined;

export type Section = { title: string; body: string };

/** A prompt's `## title` sections; text before the first heading has the title "". */
function sections(prompt: string): Section[] {
  const out: Section[] = [];
  for (const line of prompt.split("\n")) {
    if (line.startsWith("## ")) out.push({ title: line.slice(3), body: "" });
    else if (out.length)
      out[out.length - 1].body += `${out[out.length - 1].body ? "\n" : ""}${line}`;
    else if (line.trim()) out.push({ title: "", body: line });
  }
  return out.map((s) => ({ ...s, body: s.body.trim() }));
}

/**
 * What a prompt says that the previous call's didn't: its new and changed sections, and the
 * titles of the ones that stayed the same. Repeated titles are matched by position.
 */
export function promptDiff(prompt: string, previous: string) {
  const key = (list: Section[]) => {
    const seen: Record<string, number> = {};
    return list.map((s) => `${s.title}#${(seen[s.title] = (seen[s.title] ?? 0) + 1)}`);
  };
  const before = sections(previous);
  const beforeKeys = key(before);
  const now = sections(prompt);
  const changed: Section[] = [];
  const same: string[] = [];
  key(now).forEach((k, i) => {
    const old = before[beforeKeys.indexOf(k)];
    if (old?.body === now[i].body) {
      if (!same.includes(now[i].title)) same.push(now[i].title);
    } else changed.push(now[i]);
  });
  return { changed, same };
}
