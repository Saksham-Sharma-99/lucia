import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebounced } from "./use-debounced";

describe("useDebounced", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("updates only after the value settles, collapsing rapid changes", () => {
    const { result, rerender } = renderHook(({ v }) => useDebounced(v, 300), {
      initialProps: { v: "a" },
    });
    rerender({ v: "ab" });
    act(() => vi.advanceTimersByTime(200));
    rerender({ v: "abc" });
    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toBe("a");
    act(() => vi.advanceTimersByTime(100));
    expect(result.current).toBe("abc");
  });

  it("drops a pending update on unmount", () => {
    const clear = vi.spyOn(globalThis, "clearTimeout");
    const { rerender, unmount } = renderHook(({ v }) => useDebounced(v, 300), {
      initialProps: { v: 1 },
    });
    rerender({ v: 2 });
    unmount();
    expect(clear).toHaveBeenCalled();
  });
});
