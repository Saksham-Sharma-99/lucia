import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { QueryLike } from "@/lib/query";

import { QueryState } from "./query-state";

const show = (query: Partial<QueryLike<string[]>>) => {
  const full = {
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: vi.fn(),
    ...query,
  };
  render(
    <QueryState
      query={full}
      what="Agents"
      loading={<p>loading</p>}
      isEmpty={(d) => d.length === 0}
      empty={<p>none</p>}
    >
      {(d) => <p>{d.join(",")}</p>}
    </QueryState>,
  );
  return full;
};

describe("QueryState", () => {
  it("shows loading until data arrives", () => {
    show({ isPending: true });
    screen.getByText("loading");
  });

  it("a failed first load offers a retry", async () => {
    const query = show({ isError: true, error: new Error("down") });
    screen.getByText("Agents didn't load");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(query.refetch).toHaveBeenCalledOnce();
  });

  it("a failed refresh keeps the data it has, with a note", () => {
    show({ isError: true, error: new Error("down"), data: ["a", "b"] });
    screen.getByText("a,b");
    expect(screen.getByRole("status").textContent).toMatch(/Couldn't refresh/);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("shows the empty state for empty data", () => {
    show({ data: [] });
    screen.getByText("none");
  });
});
