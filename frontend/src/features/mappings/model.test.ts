import { afterEach, describe, expect, it, vi } from "vitest";

import type { VersionDetail } from "@/api/generated/types.gen";
import { VERSION_CONFIG } from "@/test/fixtures";

import { baseMinWait, bindingsFor, readLastFirm, rememberFirm } from "./model";

const version = (config: Partial<VersionDetail["config"]>) =>
  ({ config: { ...VERSION_CONFIG, ...config } }) as VersionDetail;

describe("bindingsFor", () => {
  it("keeps only the connectors the version uses", () => {
    expect(bindingsFor(version({}), { gmail: "c1", slack: "c2" })).toEqual({ gmail: "c1" });
    expect(bindingsFor(version({ capabilities: [] }), { gmail: "c1" })).toEqual({});
  });
});

describe("baseMinWait", () => {
  it("uses the shortest channel step of a ladder", () => {
    expect(
      baseMinWait(
        version({
          follow_up: {
            mode: "fixed_ladder",
            ladder: [
              { channel: "email", wait_hours: 48 },
              { channel: "voice", wait_hours: 24 },
              { action: "flag", wait_hours: 1 },
            ],
          },
        }),
      ),
    ).toBe(24);
  });

  it("uses min_hours for dynamic and 0 without follow-up", () => {
    expect(
      baseMinWait(
        version({
          follow_up: {
            mode: "dynamic",
            dynamic: {
              min_hours: 30,
              max_hours: 60,
              channels: ["email"],
              escalate_after: { attempts: 2, urgency: "P1" },
            },
          },
        }),
      ),
    ).toBe(30);
    expect(baseMinWait(version({ follow_up: { mode: "none" } }))).toBe(0);
    expect(baseMinWait(version({ follow_up: undefined }))).toBe(0);
  });
});

describe("last firm", () => {
  afterEach(() => localStorage.clear());

  it("remembers the last firm used", () => {
    expect(readLastFirm()).toBeUndefined();
    rememberFirm("firm-1");
    expect(readLastFirm()).toBe("firm-1");
  });
});

describe("last firm when storage is unavailable", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads nothing and writes nothing instead of throwing", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readLastFirm()).toBeUndefined();
    expect(() => rememberFirm("f1")).not.toThrow();
  });
});

describe("baseMinWait edges", () => {
  it("ignores action steps and handles an empty ladder", () => {
    expect(baseMinWait(version({ follow_up: { mode: "fixed_ladder", ladder: [] } }))).toBe(0);
    expect(
      baseMinWait(
        version({
          follow_up: { mode: "fixed_ladder", ladder: [{ action: "escalate", wait_hours: 5 }] },
        }),
      ),
    ).toBe(0);
  });
});
