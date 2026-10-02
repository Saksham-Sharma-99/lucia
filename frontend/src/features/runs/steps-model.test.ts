import { describe, expect, it } from "vitest";

import { planItem, step } from "@/test/runtime";

import { attemptLabel, attemptsFor, replacedBy, subagentRounds } from "./steps-model";

describe("steps model", () => {
  it("an item's attempts are its action steps, in order", () => {
    const steps = [
      step({ id: "b", seq: 3 }),
      step({ id: "llm", kind: "llm", seq: 1 }),
      step({ id: "a", seq: 2 }),
      step({ id: "other", plan_item_id: "i2", seq: 4 }),
    ];
    expect(attemptsFor(planItem(1), steps).map((s) => s.id)).toEqual(["a", "b"]);
  });

  it("a subagent's children split into rounds at each planner", () => {
    const parent = step({ id: "p", kind: "subagent", tool: null });
    const child = (role: string, seq: number, output = {}) =>
      step({ id: `${role}${seq}`, parent_step_id: "p", kind: "llm", role, seq, output });
    const steps = [
      parent,
      child("sub_planner", 1),
      child("sub_executor", 2),
      child("sub_reviewer", 3, { score: 0.3 }),
      child("sub_planner", 4),
      child("sub_executor", 5),
      child("sub_reviewer", 6, { score: 0.82 }),
    ];
    const rounds = subagentRounds(parent, steps);
    expect(rounds).toHaveLength(2);
    expect(rounds[1].map((s) => s.role)).toEqual(["sub_planner", "sub_executor", "sub_reviewer"]);
  });

  it("superseded items point to their replacements", () => {
    const plan = [planItem(1, { status: "SUPERSEDED", superseded_by: ["i3"] }), planItem(3)];
    expect(replacedBy(plan[0], plan).map((i) => i.ordinal)).toEqual([3]);
    expect(replacedBy(planItem(2), plan)).toEqual([]);
  });

  it("labels attempts from what happened", () => {
    expect(attemptLabel(step({ output: { ended_reason: "voicemail" } }), 0)).toBe(
      "Attempt 1 · voicemail",
    );
    expect(attemptLabel(step({ summary: "Called Jane" }), 1)).toBe("Attempt 2 · Called Jane");
    expect(attemptLabel(step({ status: "FAILED", summary: null }), 0)).toBe("Attempt 1 · Failed");
  });

  it("copes with items that have no steps or output", () => {
    expect(attemptsFor(planItem(1, { step_ids: undefined }), [])).toEqual([]);
  });
});
