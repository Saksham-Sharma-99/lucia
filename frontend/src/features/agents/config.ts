import { z } from "zod";

import type { VersionConfig } from "@/api/generated/types.gen";

/** `@handle`: how people call an agent. Immutable once created. */
export const handleSchema = z
  .string()
  .regex(
    /^[a-z][a-z0-9_-]{2,31}$/,
    "3–32 lowercase letters, digits, - or _, starting with a letter",
  );

/**
 * The version config as the forms edit it: every optional section filled in, so inputs are
 * always controlled. Field paths match the API's JSON pointers (`config.follow_up.ladder.0`).
 */
const urgency = z.enum(["P0", "P1", "P2"]);
const nonNegInt = (max: number) => z.number().int().min(0).max(max);

export const rungSchema = z
  .object({
    kind: z.enum(["channel", "action"]),
    channel: z.string().nullable(),
    action: z.enum(["escalate", "flag"]).nullable(),
    wait_hours: nonNegInt(24 * 60),
    attempts: z.number().int().min(1).max(10),
    urgency: urgency.nullable(),
  })
  .refine((r) => (r.kind === "channel" ? !!r.channel : !!r.action), {
    message: "Pick what this step does",
    path: ["kind"],
  });

export const configSchema = z.object({
  system_prompt: z.string().trim().min(1, "Write the system prompt").max(20000),
  models: z.object({
    loop: z.string().min(1, "Pick a model"),
    guardrail: z.string().min(1, "Pick a model"),
    judge: z.string().min(1, "Pick a model"),
  }),
  capabilities: z
    .array(z.object({ connector: z.string(), tools: z.array(z.string()).min(1, "Pick a tool") }))
    .min(1, "Pick at least one connector"),
  follow_up: z.object({
    mode: z.enum(["none", "fixed_ladder", "dynamic"]),
    ladder: z.array(rungSchema),
    dynamic: z.object({
      min_hours: z
        .number()
        .int()
        .min(1)
        .max(24 * 60),
      max_hours: z
        .number()
        .int()
        .min(1)
        .max(24 * 60),
      business_hours: z.boolean(),
      channels: z.array(z.string()),
      escalate_after: z.object({ attempts: z.number().int().min(1).max(20), urgency }),
    }),
  }),
  recurrence: z.object({ every_days: z.number().int().min(1).max(365) }).nullable(),
  end_conditions: z.object({
    max_duration_days: z.number().int().min(1).max(730),
    max_steps: z.number().int().min(10).max(5000),
    on_subject_closed: z.enum(["end", "pause"]),
  }),
  policy_pack: z.array(z.object({ rule: z.string(), params: z.record(z.string(), z.unknown()) })),
  hitl: z.object({
    ask_on: z.array(z.string()),
    verify_evidence_below: z.number().min(0).max(1),
  }),
  alert_policy: z.object({
    urgency_mode: z.enum(["auto", "fixed"]),
    fixed_urgency: urgency.nullable(),
    default_channels: z.object({
      P0: z.array(z.string()),
      P1: z.array(z.string()),
      P2: z.array(z.string()),
    }),
  }),
  max_turns_per_episode: z.number().int().min(1).max(50),
});

export type ConfigForm = z.infer<typeof configSchema>;
export type RungForm = ConfigForm["follow_up"]["ladder"][number];

export const DEFAULT_DYNAMIC: ConfigForm["follow_up"]["dynamic"] = {
  min_hours: 48,
  max_hours: 120,
  business_hours: true,
  channels: [],
  escalate_after: { attempts: 3, urgency: "P1" },
};

export function blankConfig(models: string[]): ConfigForm {
  const first = models[0] ?? "";
  return {
    system_prompt: "",
    models: { loop: first, guardrail: models[models.length - 1] ?? first, judge: first },
    capabilities: [],
    follow_up: { mode: "none", ladder: [], dynamic: DEFAULT_DYNAMIC },
    recurrence: null,
    end_conditions: { max_duration_days: 120, max_steps: 600, on_subject_closed: "end" },
    policy_pack: [],
    hitl: { ask_on: [], verify_evidence_below: 0.8 },
    alert_policy: {
      urgency_mode: "auto",
      fixed_urgency: null,
      default_channels: { P0: ["slack_dm"], P1: ["slack_thread"], P2: ["digest"] },
    },
    max_turns_per_episode: 12,
  };
}

/** Stored config -> form values (fills every section the stored JSON may omit). */
export function toForm(cfg: VersionConfig): ConfigForm {
  const base = blankConfig([cfg.models.loop]);
  const channels = cfg.alert_policy.default_channels;
  return {
    ...base,
    system_prompt: cfg.system_prompt,
    models: cfg.models,
    capabilities: cfg.capabilities,
    follow_up: {
      mode: cfg.follow_up?.mode ?? "none",
      ladder: (cfg.follow_up?.ladder ?? []).map((r) => ({
        kind: r.action ? "action" : "channel",
        channel: r.channel ?? null,
        action: r.action ?? null,
        wait_hours: r.wait_hours,
        attempts: r.attempts ?? 1,
        urgency: r.urgency ?? null,
      })),
      dynamic: cfg.follow_up?.dynamic
        ? { ...DEFAULT_DYNAMIC, ...cfg.follow_up.dynamic }
        : DEFAULT_DYNAMIC,
    },
    recurrence: cfg.recurrence ?? null,
    end_conditions: { ...base.end_conditions, ...cfg.end_conditions },
    policy_pack: (cfg.policy_pack ?? []).map((p) => ({ rule: p.rule, params: p.params ?? {} })),
    hitl: { ...base.hitl, ...cfg.hitl },
    alert_policy: {
      urgency_mode: cfg.alert_policy.urgency_mode ?? "auto",
      fixed_urgency: cfg.alert_policy.fixed_urgency ?? null,
      default_channels: { P0: channels.P0 ?? [], P1: channels.P1 ?? [], P2: channels.P2 ?? [] },
    },
    max_turns_per_episode: cfg.max_turns_per_episode ?? 12,
  };
}

/** Form values -> API config: drop what the chosen modes don't use. */
export function toPayload(f: ConfigForm): VersionConfig {
  const fu = f.follow_up;
  return {
    ...f,
    follow_up: {
      mode: fu.mode,
      ladder:
        fu.mode === "fixed_ladder"
          ? fu.ladder.map((r) =>
              r.kind === "channel"
                ? { channel: r.channel, wait_hours: r.wait_hours, attempts: r.attempts }
                : { action: r.action, wait_hours: r.wait_hours, urgency: r.urgency },
            )
          : [],
      dynamic: fu.mode === "dynamic" ? fu.dynamic : null,
    },
    alert_policy: {
      ...f.alert_policy,
      fixed_urgency: f.alert_policy.urgency_mode === "fixed" ? f.alert_policy.fixed_urgency : null,
    },
  };
}

/** The tools enabled across all capabilities. */
export function selectedTools(cfg: Pick<ConfigForm, "capabilities">): Set<string> {
  return new Set(cfg.capabilities.flatMap((c) => c.tools));
}
