import { describe, expect, it } from "vitest";

import { conversation } from "@/test/runtime";

import { groupByAge } from "./model";

describe("groupByAge", () => {
  const now = Date.parse("2026-10-20T15:00:00Z");
  const at = (iso: string, id: string) => conversation({ id, last_message_at: iso });

  it("groups chats as Today, Previous 7 days, Previous 30 days, Older", () => {
    const groups = groupByAge(
      [
        at("2026-10-20T09:00:00Z", "today"),
        at("2026-10-15T09:00:00Z", "week"),
        at("2026-10-01T09:00:00Z", "month"),
        at("2026-08-01T09:00:00Z", "old"),
      ],
      now,
    );
    expect(groups.map((g) => [g.label, g.items.map((c) => c.id)])).toEqual([
      ["Today", ["today"]],
      ["Previous 7 days", ["week"]],
      ["Previous 30 days", ["month"]],
      ["Older", ["old"]],
    ]);
  });

  it("drops empty groups", () => {
    expect(groupByAge([at("2026-10-20T09:00:00Z", "a")], now).map((g) => g.label)).toEqual([
      "Today",
    ]);
    expect(groupByAge([], now)).toEqual([]);
  });
});
