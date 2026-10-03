import { describe, expect, it } from "vitest";

import {
  KANBAN,
  canHandBack,
  canTakeOver,
  duration,
  isTerminal,
  itemProgress,
  pollEvery,
  statusLabel,
  taskTarget,
} from "./model";

describe("run model", () => {
  it("knows which runs are finished", () => {
    expect(isTerminal("COMPLETED")).toBe(true);
    expect(isTerminal("ENDED")).toBe(true);
    expect(isTerminal("AWAITING_CONFIRMATION")).toBe(false);
    expect(isTerminal("PAUSED")).toBe(false);
  });

  it("lays tasks out in six columns, failed ones with the skipped", () => {
    expect(KANBAN.map((c) => c.label)).toEqual([
      "Todo",
      "In progress",
      "Waiting",
      "Blocked",
      "Done",
      "Skipped",
    ]);
    expect(KANBAN.find((c) => (c.statuses as readonly string[]).includes("FAILED"))?.label).toBe(
      "Skipped",
    );
  });

  it("counts items: superseded don't count, skipped count as done", () => {
    const plan = [
      { status: "DONE" },
      { status: "SKIPPED" },
      { status: "SUPERSEDED" },
      { status: "PENDING" },
    ];
    expect(itemProgress(plan)).toEqual({ done: 2, total: 3 });
    expect(itemProgress([])).toEqual({ done: 0, total: 0 });
  });

  it("formats durations and targets", () => {
    const now = Date.parse("2026-10-01T12:00:00Z");
    expect(duration("2026-10-01T11:58:30Z", null, now)).toBe("1m 30s");
    expect(duration("2026-10-01T10:00:00Z", "2026-10-01T12:05:00Z", now)).toBe("2h 5m");
    expect(duration("2026-10-01T11:59:59Z", "2026-10-01T12:00:19Z", now)).toBe("20s");
    expect(duration(null, null, now)).toBe("—");
    expect(taskTarget("call-client:contact-536639ae")).toBe("contact-536639ae");
    expect(taskTarget("summary:run")).toBe("whole run");
  });
});

describe("run controls and polling", () => {
  it("polls every 3s until the run is finished", () => {
    expect(pollEvery("ACTIVE")).toBe(3000);
    expect(pollEvery("TAKEN_OVER")).toBe(3000);
    expect(pollEvery("COMPLETED")).toBe(false);
    expect(pollEvery(undefined)).toBe(false);
  });

  it("offers take over on live runs and on a run paused by failures", () => {
    expect(canTakeOver({ status: "ACTIVE", substatus: "WAITING" })).toBe(true);
    expect(canTakeOver({ status: "AWAITING_CONFIRMATION", substatus: null })).toBe(true);
    expect(canTakeOver({ status: "PAUSED", substatus: "repeated_failure" })).toBe(true);
    expect(canTakeOver({ status: "PAUSED", substatus: "kill_switch" })).toBe(false);
    expect(canTakeOver({ status: "COMPLETED", substatus: null })).toBe(false);
    expect(canHandBack({ status: "TAKEN_OVER" })).toBe(true);
    expect(canHandBack({ status: "ACTIVE" })).toBe(false);
  });

  it("reads statuses as words", () => {
    expect(statusLabel("AWAITING_CONFIRMATION")).toBe("Awaiting confirmation");
    expect(statusLabel("IN_PROGRESS")).toBe("In progress");
    expect(statusLabel("SUCCEEDED")).toBe("Succeeded");
    expect(statusLabel("user_input")).toBe("User input");
  });
});
