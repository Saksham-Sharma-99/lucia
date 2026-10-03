import { describe, expect, it } from "vitest";

import { hours, hueFor, initials, relativeTime, shortHash } from "./format";

describe("hours", () => {
  it.each([
    [0, "now"],
    [5, "5h"],
    [24, "1d"],
    [49, "2d 1h"],
    [168, "7d"],
    [1.5, "1h 30m"],
    [0.1, "6m"],
    [0.12, "7m"],
  ])("%d -> %s", (h, text) => expect(hours(h)).toBe(text));
});

describe("relativeTime", () => {
  const now = Date.parse("2026-10-01T12:00:00Z");
  it("reads past and future and handles missing values", () => {
    expect(relativeTime("2026-10-01T11:00:00Z", now)).toBe("1 hour ago");
    expect(relativeTime("2026-09-29T12:00:00Z", now)).toBe("2 days ago");
    expect(relativeTime("2026-10-01T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-10-02T12:00:00Z", now)).toBe("tomorrow");
    expect(relativeTime(null, now)).toBe("never");
  });
});

describe("initials / hue / hash", () => {
  it("takes two initials from words or one word", () => {
    expect(initials("Medical Records Follow-up")).toBe("MR");
    expect(initials("orchestrator")).toBe("OR");
    expect(initials("Smith & Associates")).toBe("SA");
    expect(initials("")).toBe("");
  });

  it("gives a key the same hue every time", () => {
    expect(hueFor("records")).toBe(hueFor("records"));
    expect(typeof hueFor("")).toBe("number");
  });

  it("shortens hashes", () => expect(shortHash("5be3d12ea7bb")).toBe("5be3d12e"));
});
