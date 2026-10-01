import { describe, expect, it } from "vitest";

import type { PlatformStatus } from "@/api/generated/types.gen";

import { isConfigured, settingsSchema, slugify } from "./model";

describe("slugify", () => {
  it.each([
    ["Smith & Associates", "smith-and-associates"],
    ["  Johnson   Legal, LLP!  ", "johnson-legal-llp"],
    ["--Already-Slugged--", "already-slugged"],
    ["Café Ñu", "caf-u"],
    ["!!!", ""],
    ["", ""],
  ])("%j -> %j", (name, slug) => expect(slugify(name)).toBe(slug));

  it("caps at 40 characters without a trailing dash", () => {
    const slug = slugify("a".repeat(39) + " bcd");
    expect(slug.length).toBeLessThanOrEqual(40);
    expect(slug.endsWith("-")).toBe(false);
  });
});

describe("isConfigured", () => {
  const platform = {
    slack: true,
    google: false,
    vapi: true,
    twilio: true,
    public_base_url: "",
    allowed_models: [],
    drafter_enabled: false,
  } satisfies PlatformStatus;
  it("follows the platform flag for known connectors", () => {
    expect(isConfigured(platform, "slack")).toBe(true);
    expect(isConfigured(platform, "gmail")).toBe(false);
  });
  it("assumes configured while unknown (status not loaded, or a connector without setup)", () => {
    expect(isConfigured(undefined, "gmail")).toBe(true);
    expect(isConfigured(platform, "fax")).toBe(true);
  });
});

describe("settingsSchema", () => {
  const valid = {
    business_hours: { mon: { start: "09:00", end: "18:00" }, sat: null },
    quiet_hours: { start: "20:00", end: "08:00" },
    alert_routing: { P0: ["slack_dm"], P1: [], P2: ["digest"] },
    policy_floor: [],
  };
  const issues = (over: object) =>
    settingsSchema
      .safeParse({ ...valid, ...over })
      .error?.issues.map((i) => `${i.path.join(".")}: ${i.message}`) ?? [];

  it("accepts a normal week and wrapping quiet hours", () => expect(issues({})).toEqual([]));
  it("rejects business hours that close before they open", () =>
    expect(issues({ business_hours: { mon: { start: "18:00", end: "09:00" } } })).toEqual([
      "business_hours.mon.end: Opens before it closes",
    ]));
  it("rejects empty quiet hours and bad times", () => {
    expect(issues({ quiet_hours: { start: "08:00", end: "08:00" } })).toEqual([
      "quiet_hours.end: Start and end differ",
    ]);
    expect(issues({ quiet_hours: { start: "8am", end: "08:00" } })).toContain(
      "quiet_hours.start: Use HH:MM",
    );
  });
  it("rejects unknown alert channels", () =>
    expect(issues({ alert_routing: { P0: ["pager"], P1: [], P2: [] } })).toHaveLength(1));
});
