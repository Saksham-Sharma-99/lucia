import { describe, expect, it } from "vitest";

import { episode, planItem, step, task } from "@/test/runtime";

import {
  attemptLabel,
  attemptsFor,
  flowRows,
  previousCall,
  promptDiff,
  replacedBy,
  subagentRounds,
} from "./steps-model";

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

  it("a model call's previous one is the latest earlier call of its role in its task", () => {
    const llm = (id: string, role: string, seq: number, task_id = "t1") =>
      step({ id, kind: "llm", role, seq, task_id });
    const steps = [
      llm("p1", "planner", 1),
      llm("x", "executor", 2),
      llm("p2", "planner", 3),
      llm("other", "planner", 4, "t2"),
      llm("p3", "planner", 5),
    ];
    expect(previousCall(steps[4], steps)?.id).toBe("p2");
    expect(previousCall(steps[0], steps)).toBeUndefined();
    expect(previousCall(steps[1], steps)).toBeUndefined();
    expect(previousCall(steps[3], steps)).toBeUndefined();
  });

  it("a prompt's diff is its new and changed sections; the rest are named", () => {
    const before = "## goal\nCall Jane\n\n## plan\n[]\n\n## old\ngone";
    const after = "## goal\nCall Jane\n\n## plan\n[i1]\n\n## errors\nuses 0";
    expect(promptDiff(after, before)).toEqual({
      changed: [
        { title: "plan", body: "[i1]" },
        { title: "errors", body: "uses 0" },
      ],
      same: ["goal"],
    });
    expect(promptDiff(before, before)).toEqual({ changed: [], same: ["goal", "plan", "old"] });
  });

  it("repeated headings are compared by position, and text before any heading counts", () => {
    const before = "intro\n## Goal\na\n## Goal\nb";
    const after = "intro\n## Goal\na\n## Goal\nc";
    expect(promptDiff(after, before)).toEqual({
      changed: [{ title: "Goal", body: "c" }],
      same: ["", "Goal"],
    });
  });

  describe("flow rows", () => {
    const at = (m: number) => new Date(Date.UTC(2026, 9, 1, 11, m)).toISOString();
    const trigger = episode({ id: "e1", created_at: at(0), started_at: at(0) });
    const report = episode({
      id: "e2",
      task_id: "t1",
      trigger_type: "external_response",
      created_at: at(30),
      started_at: at(30),
    });
    const llm = (id: string, role: string, seq: number, ep: string, m: number) =>
      step({
        id,
        kind: "llm",
        role,
        tool: null,
        plan_item_id: null,
        seq,
        episode_id: ep,
        started_at: at(m),
      });
    const shape = (rows: ReturnType<typeof flowRows>) =>
      rows.map((r) => [r.item?.id ?? r.title, r.notes.map((n) => n.label)]);

    it("the plan's items follow its header; plan writes point at the header", () => {
      const steps = [llm("p1", "planner", 1, "e1", 1), llm("p2", "planner", 2, "e1", 2)];
      const rows = flowRows(task({ plan: [planItem(1), planItem(2)] }), steps, [trigger]);
      expect(shape(rows)).toEqual([
        ["Plan", ["Plan written", "Plan revised"]],
        ["i1", []],
        ["i2", []],
      ]);
    });

    it("an episode points at the step running when it arrived; events at their own item", () => {
      const steps = [
        llm("p1", "planner", 1, "e1", 1),
        step({
          id: "c",
          seq: 2,
          plan_item_id: "i1",
          episode_id: "e1",
          status: "AWAITING_CALLBACK",
          started_at: at(5),
          ended_at: null,
        }),
        llm("r", "relevance", 3, "e2", 31),
      ];
      const journal = [
        {
          id: "j",
          task_id: "t1",
          episode_id: "e2",
          source: "harness",
          text: "Jane is better",
          created_at: at(32),
        },
      ];
      const rows = flowRows(
        task({ plan: [planItem(1), planItem(2)] }),
        steps,
        [trigger, report],
        journal,
      );
      expect(shape(rows)).toEqual([
        ["Plan", ["Plan written"]],
        [
          "i1",
          [
            "Call placed",
            "Episode arrived",
            "Checked what's still needed",
            "Journal entry created",
          ],
        ],
        ["i2", []],
      ]);
      const arrivedNote = rows[1].notes[1];
      expect([arrivedNote.trigger, arrivedNote.detail]).toEqual([
        "external_response",
        "External response",
      ]);
    });

    it("an episode that appended items points at their header, with the plan revision", () => {
      // Real steps rarely carry an episode id: rounds follow planner bursts and arrival times.
      const steps = [
        llm("p1", "planner", 1, "", 1),
        llm("p2", "planner", 2, "", 2),
        step({
          id: "c",
          seq: 3,
          plan_item_id: "i1",
          episode_id: null,
          started_at: at(5),
          ended_at: at(20),
        }),
        llm("r", "relevance", 4, "e2", 31),
        llm("p3", "planner", 5, "", 32),
        step({
          id: "s",
          seq: 6,
          kind: "subagent",
          tool: "harness.subagent",
          plan_item_id: "i2",
          episode_id: null,
          started_at: at(33),
        }),
      ];
      const plan = [planItem(1, { status: "DONE" }), planItem(2, { added_in: 1 })];
      const rows = flowRows(task({ plan }), steps, [trigger, report]);
      expect(shape(rows)).toEqual([
        ["Plan", ["Plan written", "Plan revised"]],
        ["i1", ["Call placed"]],
        ["Added", ["Episode arrived", "Checked what's still needed", "Plan revised"]],
        ["i2", ["Subagent wrote a draft"]],
      ]);
    });

    it("an episode with nothing running points at the next item due", () => {
      const steps = [
        step({
          id: "c",
          seq: 1,
          plan_item_id: "i1",
          episode_id: "e1",
          started_at: at(5),
          ended_at: at(10),
        }),
      ];
      const plan = [planItem(1, { status: "DONE" }), planItem(2)];
      const rows = flowRows(task({ plan }), steps, [trigger, report]);
      expect(rows.find((r) => r.item?.id === "i2")?.notes.map((n) => n.label)).toEqual([
        "Episode arrived",
      ]);
    });

    it("a finished step without an end time doesn't keep its item running", () => {
      const steps = [
        step({
          id: "f",
          seq: 1,
          tool: "harness.emit_finding",
          plan_item_id: "i1",
          status: "SUCCEEDED",
          started_at: at(5),
          ended_at: null,
        }),
      ];
      const rows = flowRows(task({ plan: [planItem(1, { status: "DONE" }), planItem(2)] }), steps, [
        trigger,
        report,
      ]);
      expect(rows.find((r) => r.item?.id === "i2")?.notes.map((n) => n.label)).toEqual([
        "Episode arrived",
      ]);
    });

    it("a wake-up that hasn't fired yet says so, at its due time", () => {
      const wake = episode({
        id: "e3",
        task_id: "t1",
        trigger_type: "scheduled",
        status: "scheduled",
        created_at: at(2),
        started_at: null,
        ended_at: null,
        due_at: at(90),
      });
      const rows = flowRows(task({ plan: [planItem(1)] }), [], [trigger, wake]);
      expect(rows[1].notes.map((n) => [n.label, n.at])).toEqual([["Wake-up scheduled", at(90)]]);
    });

    it("drops summaries that repeat the label and other tasks' journal entries", () => {
      const steps = [
        step({ id: "c", summary: "Call placed", episode_id: "e1", started_at: at(5) }),
      ];
      const journal = [
        {
          id: "j",
          task_id: "t2",
          episode_id: null,
          source: "harness",
          text: "x",
          created_at: at(6),
        },
      ];
      const rows = flowRows(task({ plan: [planItem(1)] }), steps, [trigger], journal);
      expect(rows[1].notes).toEqual([
        { id: "c", at: at(5), label: "Call placed", detail: null, status: "SUCCEEDED" },
      ]);
    });
  });
});
