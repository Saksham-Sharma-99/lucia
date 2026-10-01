import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiffView } from "./diff-view";

describe("DiffView", () => {
  it("says so when nothing changed", () => {
    render(<DiffView entries={[]} />);
    screen.getByText("These versions have the same config.");
  });

  it("groups by section and shows removed, added and changed values", () => {
    render(
      <DiffView
        entries={[
          { path: "/system_prompt", op: "change", before: "Old", after: "New" },
          { path: "/policy_pack/2", op: "add", after: { rule: "opt_out_enforced" } },
          { path: "/recurrence", op: "remove", before: { every_days: 14 } },
        ]}
      />,
    );
    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
      "Prompt",
      "Policy rules",
      "Repeats",
    ]);
    screen.getByText("Old");
    screen.getByText("New");
    screen.getByText('{"rule":"opt_out_enforced"}');
    screen.getByText('{"every_days":14}');
    expect(screen.getAllByLabelText("removed")).toHaveLength(2); // the change and the removal
    expect(screen.getAllByLabelText("added")).toHaveLength(2); // the change and the addition
  });
});
