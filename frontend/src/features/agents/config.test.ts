import { describe, expect, it } from "vitest";

import { VERSION_CONFIG } from "@/test/fixtures";

import {
  DEFAULT_DYNAMIC,
  blankConfig,
  configSchema,
  selectedTools,
  toForm,
  toPayload,
} from "./config";

describe("toForm", () => {
  it("fills every section a stored config may omit", () => {
    const form = toForm(VERSION_CONFIG);
    expect(form.end_conditions).toEqual({
      max_duration_days: 120,
      max_steps: 600,
      on_subject_closed: "end",
    });
    expect(form.hitl).toEqual({ ask_on: [], verify_evidence_below: 0.8 });
    expect(form.alert_policy.default_channels).toEqual({ P0: ["slack_dm"], P1: [], P2: [] });
    expect(form.follow_up.dynamic).toEqual(DEFAULT_DYNAMIC);
    expect(form.recurrence).toBeNull();
    expect(form.max_turns_per_episode).toBe(12);
  });

  it("tags ladder rungs by kind", () => {
    const [email, escalate] = toForm(VERSION_CONFIG).follow_up.ladder;
    expect(email).toMatchObject({ kind: "channel", channel: "email", attempts: 2 });
    expect(escalate).toMatchObject({
      kind: "action",
      action: "escalate",
      urgency: "P1",
      attempts: 1,
    });
  });
});

describe("toPayload", () => {
  it("round-trips a stored config's sections", () => {
    const payload = toPayload(toForm(VERSION_CONFIG));
    expect(payload.follow_up?.ladder).toEqual(VERSION_CONFIG.follow_up?.ladder);
    expect(payload.capabilities).toEqual(VERSION_CONFIG.capabilities);
    expect(payload.follow_up?.dynamic).toBeNull();
  });

  it("drops the ladder unless the mode uses it", () => {
    const form = toForm(VERSION_CONFIG);
    form.follow_up.mode = "dynamic";
    const payload = toPayload(form);
    expect(payload.follow_up?.ladder).toEqual([]);
    expect(payload.follow_up?.dynamic).toEqual(DEFAULT_DYNAMIC);
    form.follow_up.mode = "none";
    expect(toPayload(form).follow_up).toEqual({ mode: "none", ladder: [], dynamic: null });
  });

  it("only sends fixed_urgency in fixed mode", () => {
    const form = toForm(VERSION_CONFIG);
    form.alert_policy.fixed_urgency = "P0";
    expect(toPayload(form).alert_policy.fixed_urgency).toBeNull();
    form.alert_policy.urgency_mode = "fixed";
    expect(toPayload(form).alert_policy.fixed_urgency).toBe("P0");
  });
});

describe("configSchema", () => {
  it("accepts a stored config once filled in", () => {
    expect(configSchema.safeParse(toForm(VERSION_CONFIG)).success).toBe(true);
  });

  it("rejects an empty blank config with field paths", () => {
    const result = configSchema.safeParse(blankConfig(["m"]));
    expect(result.success).toBe(false);
    const paths = result.error?.issues.map((i) => i.path.join(".")) ?? [];
    expect(paths).toEqual(expect.arrayContaining(["system_prompt", "capabilities"]));
  });

  it("requires a rung to say what it does", () => {
    const form = toForm(VERSION_CONFIG);
    form.follow_up.ladder[0] = { ...form.follow_up.ladder[0], channel: null };
    const issues = configSchema.safeParse(form).error?.issues ?? [];
    expect(issues.map((i) => i.path.join("."))).toContain("follow_up.ladder.0.kind");
  });

  it.each([
    ["max_turns_per_episode", 51],
    ["max_turns_per_episode", 0],
  ])("bounds %s (%i)", (key, value) => {
    expect(configSchema.safeParse({ ...toForm(VERSION_CONFIG), [key]: value }).success).toBe(false);
  });
});

describe("blankConfig / selectedTools", () => {
  it("picks the first model for loop and judge, the last for guardrail", () => {
    expect(blankConfig(["big", "small"]).models).toEqual({
      loop: "big",
      guardrail: "small",
      judge: "big",
    });
    expect(blankConfig([]).models).toEqual({ loop: "", guardrail: "", judge: "" });
  });

  it("flattens tools across connectors", () => {
    expect([
      ...selectedTools({
        capabilities: [
          { connector: "a", tools: ["a.x"] },
          { connector: "b", tools: ["b.y", "b.z"] },
        ],
      }),
    ]).toEqual(["a.x", "b.y", "b.z"]);
  });
});

describe("recurrence", () => {
  it("keeps a round limit through the form, and validates it", () => {
    const cfg = { ...VERSION_CONFIG, recurrence: { every_days: 0.005, max_cycles: 2 } };
    expect(toPayload(toForm(cfg)).recurrence).toEqual({ every_days: 0.005, max_cycles: 2 });
    const form = toForm(cfg);
    expect(configSchema.safeParse(form).success).toBe(true);
    const zero = { ...form, recurrence: { every_days: 1, max_cycles: 0 } };
    expect(configSchema.safeParse(zero).success).toBe(false);
  });
});
