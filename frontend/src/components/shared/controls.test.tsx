import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { CheckboxGroup, NumberInput, TagInput } from "./controls";

function StatefulNumber({
  onChange,
  initial = 3,
}: {
  onChange: (v: number) => void;
  initial?: number;
}) {
  const [v, setV] = useState(initial);
  return (
    <NumberInput
      aria-label="n"
      value={v}
      min={1}
      onChange={(n) => {
        setV(n);
        onChange(n);
      }}
    />
  );
}

describe("NumberInput", () => {
  it("lets you clear and retype without snapping to the minimum", async () => {
    const onChange = vi.fn();
    render(<StatefulNumber onChange={onChange} />);
    const input = screen.getByLabelText("n");
    await userEvent.clear(input);
    expect((input as HTMLInputElement).value).toBe("");
    await userEvent.type(input, "5");
    expect(onChange).toHaveBeenLastCalledWith(5);
  });

  it("raises a number below the minimum to it on leaving", async () => {
    const onChange = vi.fn();
    render(<StatefulNumber onChange={onChange} />);
    const input = screen.getByLabelText("n");
    await userEvent.clear(input);
    await userEvent.type(input, "0");
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(1);
    expect((input as HTMLInputElement).value).toBe("1");
  });

  it("restores the last valid number when left empty", async () => {
    const onChange = vi.fn();
    render(<StatefulNumber onChange={onChange} />);
    const input = screen.getByLabelText("n");
    await userEvent.clear(input);
    await userEvent.tab();
    expect((input as HTMLInputElement).value).toBe("3");
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("TagInput", () => {
  it("adds on Enter, ignores duplicates and blanks, removes with ×", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<TagInput value={["a"]} onChange={onChange} placeholder="add" />);
    const input = screen.getByPlaceholderText("add");
    await userEvent.type(input, "b{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["a", "b"]);
    onChange.mockClear();
    await userEvent.type(input, "a{Enter}   {Enter}");
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Remove a" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
    rerender(<TagInput value={["a", "b"]} onChange={onChange} placeholder="add" max={2} />);
    expect(screen.queryByPlaceholderText("add")).toBeNull();
  });

  it("is read-only when disabled", () => {
    render(<TagInput value={["a"]} onChange={vi.fn()} disabled placeholder="add" />);
    expect(screen.queryByRole("button", { name: "Remove a" })).toBeNull();
    expect(screen.queryByPlaceholderText("add")).toBeNull();
  });
});

describe("CheckboxGroup", () => {
  it("keeps the options' order in the value", async () => {
    const onChange = vi.fn();
    const options = [
      { value: "x", label: "X" },
      { value: "y", label: "Y" },
      { value: "z", label: "Z" },
    ];
    render(<CheckboxGroup value={["z"]} onChange={onChange} options={options} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "X" }));
    expect(onChange).toHaveBeenLastCalledWith(["x", "z"]);
  });
});
