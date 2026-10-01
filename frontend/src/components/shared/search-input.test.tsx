import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchInput } from "./search-input";

/** Stands in for the URL: commits land in `value` like a search-param round trip. */
function Harness({ onCommit }: { onCommit: (q?: string) => void }) {
  const [value, setValue] = useState<string | undefined>("old");
  return (
    <>
      <SearchInput
        label="Search"
        value={value}
        onCommit={(q) => {
          onCommit(q);
          setValue(q);
        }}
      />
      <button onClick={() => setValue(undefined)}>clear</button>
    </>
  );
}

describe("SearchInput", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());
  const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const box = () => screen.getByLabelText("Search") as HTMLInputElement;

  it("commits once typing pauses", async () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    await user().clear(box());
    await user().type(box(), "rec");
    expect(onCommit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith("rec");
  });

  it("an emptied box clears the param", async () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    await user().clear(box());
    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });

  it("the URL echoing a commit doesn't undo newer typing", async () => {
    render(<Harness onCommit={vi.fn()} />);
    await user().type(box(), "s");
    act(() => vi.advanceTimersByTime(300)); // commits "olds"; the URL echoes it
    await user().type(box(), "x");
    expect(box().value).toBe("oldsx");
  });

  it("a URL change mid-typing wins over the pending commit", async () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    await user().type(box(), "s");
    await user().click(screen.getByRole("button", { name: "clear" })); // e.g. Back
    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).not.toHaveBeenCalled();
    expect(box().value).toBe("");
  });

  it("follows the URL when it changes elsewhere", async () => {
    render(<Harness onCommit={vi.fn()} />);
    await user().click(screen.getByRole("button", { name: "clear" }));
    expect(box().value).toBe("");
  });
});
