import { describe, expect, it, vi } from "vitest";

import { allOf, type QueryLike } from "./query";

const q = <T>(over: Partial<QueryLike<T>> = {}): QueryLike<T> => ({
  isPending: false,
  isError: false,
  error: null,
  data: undefined,
  refetch: vi.fn(),
  ...over,
});

describe("allOf", () => {
  it("has data only once every query has data", () => {
    expect(allOf({ a: q({ data: 1 }), b: q({ isPending: true }) })).toMatchObject({
      isPending: true,
      data: undefined,
    });
    expect(allOf({ a: q({ data: 1 }), b: q({ data: "x" }) }).data).toEqual({ a: 1, b: "x" });
  });

  it("reports the first error and retries only the failed queries", async () => {
    const ok = q({ data: 1 });
    const bad = q({ isError: true, error: "boom" });
    const all = allOf({ ok, bad });
    expect(all).toMatchObject({ isError: true, error: "boom" });
    await all.refetch();
    expect(bad.refetch).toHaveBeenCalledOnce();
    expect(ok.refetch).not.toHaveBeenCalled();
  });

  it("keeps falsy data such as 0 or an empty list", () => {
    expect(allOf({ n: q({ data: 0 }), l: q({ data: [] }) }).data).toEqual({ n: 0, l: [] });
  });
});
