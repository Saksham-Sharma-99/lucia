/** Data builders for the runtime pages: chats, runs, tasks, steps, subjects, notifications. */
import type {
  ContactPointOut,
  ConversationOut,
  EpisodeOut,
  JournalOut,
  LinkedRun,
  LogOut,
  MentionableAgent,
  MessageOut,
  NotificationOut,
  RunOut,
  StepOut,
  StepResultOut,
  SubjectContactOut,
  SubjectDetail,
  SubjectOut,
  TaskOut,
} from "@/api/generated/types.gen";

const NOW = "2026-10-01T12:00:00Z";

export const conversation = (over: Partial<ConversationOut> = {}): ConversationOut => ({
  id: "c1",
  firm_id: "f1",
  channel: "playground",
  subject_id: null,
  subject_title: null,
  title: "Jane check-in",
  pending: null,
  last_message_at: NOW,
  created_at: NOW,
  ...over,
});

export const message = (over: Partial<MessageOut> = {}): MessageOut => ({
  id: "msg1",
  conversation_id: "c1",
  direction: "inbound",
  actor: "human",
  author_user_id: "u1",
  external_author: null,
  agent_id: null,
  run_id: null,
  body: "@checkin call Jane",
  mentions: ["checkin"],
  blocks: [],
  status: "received",
  created_at: NOW,
  ...over,
});

export const linkedRun = (over: Partial<LinkedRun> = {}): LinkedRun => ({
  id: "r1",
  agent_handle: "checkin",
  status: "ACTIVE",
  substatus: "WAITING",
  tasks_done: 1,
  tasks_total: 2,
  ...over,
});

export const mentionable = (over: Partial<MentionableAgent> = {}): MentionableAgent => ({
  handle: "checkin",
  name: "Client check-in",
  description: "Calls clients for a check-in",
  ...over,
});

export const run = (over: Partial<RunOut> = {}): RunOut => ({
  id: "r1",
  firm_id: "f1",
  agent_handle: "checkin",
  subject_id: "subj1",
  subject_title: "Doe v. Acme Trucking",
  status: "ACTIVE",
  substatus: "WAITING",
  goal: "Check in with Jane",
  completion_criteria: "Jane is reached and her update is recorded",
  version: 2,
  cycle: 0,
  next_wake_at: null,
  started_at: NOW,
  ended_at: null,
  ended_reason: null,
  takeover: null,
  tasks_done: 1,
  tasks_total: 2,
  created_at: NOW,
  updated_at: NOW,
  ...over,
});

export const planItem = (n: number, over: Record<string, unknown> = {}) => ({
  id: `i${n}`,
  ordinal: n,
  title: `Item ${n}`,
  kind: "tool",
  tool: "vapi.place_call",
  input_hint: "",
  status: "PENDING",
  attempts: 0,
  step_ids: [] as string[],
  output: null,
  uses: [] as string[],
  ...over,
});

export const task = (over: Partial<TaskOut> = {}): TaskOut => ({
  id: "t1",
  key: "call-client:contact-1",
  kind: "call_client",
  title: "Call Jane",
  goal: "Find out how Jane is doing",
  status: "IN_PROGRESS",
  depends_on: [],
  plan: [planItem(1)],
  output: null,
  follow_up: {},
  started_at: NOW,
  ended_at: null,
  created_at: NOW,
  ...over,
});

export const step = (over: Partial<StepOut> = {}): StepOut => ({
  id: "st1",
  task_id: "t1",
  episode_id: null,
  plan_item_id: "i1",
  parent_step_id: null,
  seq: 1,
  kind: "tool",
  role: null,
  tool: "vapi.place_call",
  status: "SUCCEEDED",
  input: {},
  output: {},
  summary: null,
  error: null,
  model: null,
  latency_ms: null,
  input_tokens: null,
  output_tokens: null,
  cost: null,
  started_at: NOW,
  ended_at: NOW,
  ...over,
});

export const log = (over: Partial<LogOut> = {}): LogOut => ({
  id: "l1",
  task_id: "t1",
  step_id: "st1",
  level: "info",
  stage: "executor",
  message: "Calling Jane",
  at: NOW,
  ...over,
});

export const episode = (over: Partial<EpisodeOut> = {}): EpisodeOut => ({
  id: "e1",
  task_id: null,
  trigger_type: "user_input",
  source: null,
  status: "completed",
  dedup_key: "msg:1",
  due_at: null,
  reason: null,
  outcome: "triaged",
  started_at: NOW,
  ended_at: NOW,
  created_at: NOW,
  ...over,
});

export const journal = (over: Partial<JournalOut> = {}): JournalOut => ({
  summary: null,
  entries: [],
  ...over,
});

export const stepResult = (over: Partial<StepResultOut> = {}): StepResultOut => ({
  id: "sr1",
  run_id: "r1",
  task_id: "t1",
  type: "attention",
  kind: "question",
  urgency: "P1",
  summary: "Which number should I call?",
  data: {},
  options: [],
  blocking: true,
  status: "open",
  answer: null,
  answered_at: null,
  created_at: NOW,
  ...over,
});

export const subject = (over: Partial<SubjectOut> = {}): SubjectOut => ({
  id: "subj1",
  firm_id: "f1",
  kind: "matter",
  title: "Doe v. Acme Trucking",
  external_ref: "DOE-2026-001",
  status: "open",
  description: "",
  data: {},
  revision: 1,
  created_at: NOW,
  updated_at: NOW,
  contact_count: 1,
  live_run_count: 1,
  ...over,
});

export const contactPoint = (over: Partial<ContactPointOut> = {}): ContactPointOut => ({
  id: "cp1",
  name: "Jane Doe",
  org_name: null,
  emails: ["jane@example.com"],
  phones: [{ e164: "+15551234567", type: "voice", label: "" }],
  tz: "America/New_York",
  opt_out: {},
  org_daily_cap: null,
  roles: [],
  ...over,
});

export const subjectContact = (over: Partial<SubjectContactOut> = {}): SubjectContactOut => ({
  id: "sc1",
  role: "client",
  consent: { voice: { status: "granted" } },
  alias_ordinal: 1,
  contact_point: contactPoint(),
  ...over,
});

export const subjectDetail = (over: Partial<SubjectDetail> = {}): SubjectDetail => ({
  ...subject(),
  contacts: [subjectContact()],
  runs: [{ id: "r1", agent_handle: "checkin", status: "ACTIVE" }],
  ...over,
});

export const notification = (over: Partial<NotificationOut> = {}): NotificationOut => ({
  id: "n1",
  run_id: "r1",
  step_result_id: "sr1",
  summary: "@checkin needs your input on Doe v. Acme Trucking",
  urgency: "P1",
  read_at: null,
  created_at: NOW,
  ...over,
});
