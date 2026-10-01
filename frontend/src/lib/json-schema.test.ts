import { describe, expect, it } from "vitest";

import {
  TIME_PATTERN,
  defaultParams,
  label,
  orderedProperties,
  paramSummary,
  paramsSummary,
} from "./json-schema";

const quietHours = {
  type: "object",
  required: ["start", "end", "tz"],
  // JSONB storage sorts keys like this; `required` keeps the author's order.
  properties: {
    tz: { type: "string", enum: ["recipient", "firm"] },
    end: { type: "string", pattern: TIME_PATTERN },
    start: { type: "string", pattern: TIME_PATTERN },
  },
};

describe("orderedProperties", () => {
  it("puts required keys first in their order, then the rest", () => {
    expect(orderedProperties(quietHours).map(([k]) => k)).toEqual(["start", "end", "tz"]);
    expect(
      orderedProperties({ required: ["b"], properties: { a: {}, b: {} } }).map(([k]) => k),
    ).toEqual(["b", "a"]);
  });

  it("ignores required keys with no property and empty schemas", () => {
    expect(orderedProperties({ required: ["ghost"], properties: {} })).toEqual([]);
    expect(orderedProperties({})).toEqual([]);
  });
});

describe("defaultParams", () => {
  it("gives every property a valid starting value", () => {
    expect(defaultParams(quietHours)).toEqual({ start: "20:00", end: "08:00", tz: "recipient" });
    expect(
      defaultParams({
        properties: {
          n: { type: "integer", minimum: 1 },
          channel: { type: "array", items: { enum: ["email", "voice"] } },
          tags: { type: "array" },
          on: { type: "boolean" },
          note: { type: "string" },
        },
      }),
    ).toEqual({ n: 1, channel: ["email"], tags: [], on: false, note: "" });
  });

  it("returns nothing for rules without params", () =>
    expect(defaultParams({ properties: {} })).toEqual({}));
});

describe("label", () => {
  it("names known keys and humanises the rest", () => {
    expect(label("tz")).toBe("Timezone");
    expect(label("n")).toBe("Limit");
    expect(label("doc_kind")).toBe("Doc kind");
  });
});

describe("paramSummary", () => {
  it.each([
    [{ enum: ["recipient", "firm"] }, "recipient | firm"],
    [{ type: "array", items: { enum: ["email", "voice"] } }, "[email, voice]"],
    [{ type: "string", pattern: TIME_PATTERN }, "time (HH:MM)"],
    [{ type: "integer" }, "integer"],
  ])("%j reads as %s", (schema, text) => expect(paramSummary(schema)).toBe(text));

  it("summarises a whole schema, or says it has none", () => {
    expect(paramsSummary(quietHours)).toBe(
      "start: time (HH:MM); end: time (HH:MM); tz: recipient | firm",
    );
    expect(paramsSummary({ type: "object", properties: {} })).toBe("no settings");
    expect(paramsSummary({ type: "object", additionalProperties: { type: "array" } })).toBe(
      "roles per document kind",
    );
  });
});
