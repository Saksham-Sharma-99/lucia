import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { isDisabled } from "@/test/dom";

import { Pagination } from "./pagination";

const button = (name: string) => screen.getByRole("button", { name });

describe("Pagination", () => {
  it("shows the range and turns pages", async () => {
    const onPage = vi.fn();
    render(<Pagination page={2} limit={20} total={45} onPage={onPage} />);
    screen.getByText("21–40 of 45");
    await userEvent.click(button("Next page"));
    await userEvent.click(button("Previous page"));
    expect(onPage.mock.calls).toEqual([[3], [1]]);
  });

  it("a single page shows the count without arrows", () => {
    render(<Pagination page={1} limit={20} total={18} onPage={vi.fn()} />);
    screen.getByText("18 in total");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("can't go before the first or past the last page", () => {
    const { rerender } = render(<Pagination page={1} limit={20} total={45} onPage={vi.fn()} />);
    expect(isDisabled(button("Previous page"))).toBe(true);
    rerender(<Pagination page={3} limit={20} total={45} onPage={vi.fn()} />);
    screen.getByText("41–45 of 45");
    expect(isDisabled(button("Next page"))).toBe(true);
  });

  it("a page past the end offers the first page", async () => {
    const onPage = vi.fn();
    render(<Pagination page={9} limit={20} total={45} onPage={onPage} />);
    screen.getByText(/Page 9 is past the end/);
    await userEvent.click(button("Go to the first page"));
    expect(onPage).toHaveBeenCalledWith(1);
  });

  it("renders nothing without results", () => {
    const { container } = render(<Pagination page={1} limit={20} total={0} onPage={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });
});
