import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { invalidate } from "./invalidate";

describe("invalidate", () => {
  it("marks only queries of the named operations stale, whatever their params", async () => {
    const qc = new QueryClient();
    const keys = [
      [{ _id: "listAgents", query: { page: 1 } }],
      [{ _id: "listAgents", query: { page: 2 } }],
      [{ _id: "getAgent", path: { handle: "x" } }],
      [{ _id: "listFirms" }],
      ["plain-key"],
    ];
    keys.forEach((k) => qc.setQueryData(k, 1));
    await invalidate(qc, "listAgents", "getAgent");
    const stale = keys.map((k) => qc.getQueryState(k)?.isInvalidated);
    expect(stale).toEqual([true, true, true, false, false]);
  });
});
