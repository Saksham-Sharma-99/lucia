import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { isDisabled } from "@/test/dom";
import { CONNECTORS } from "@/test/fixtures";

import { ToolPicker } from "./tool-picker";

describe("ToolPicker", () => {
  it("checking a connector enables all its tools", async () => {
    const onChange = vi.fn();
    render(<ToolPicker connectors={CONNECTORS} value={[]} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: /^GMAIL/ }));
    expect(onChange).toHaveBeenLastCalledWith([
      { connector: "gmail", tools: ["gmail.send_email", "gmail.read_thread"] },
    ]);
  });

  it("unchecking the last tool drops the connector", async () => {
    const onChange = vi.fn();
    render(
      <ToolPicker
        connectors={CONNECTORS}
        value={[{ connector: "gmail", tools: ["gmail.send_email"] }]}
        onChange={onChange}
      />,
    );
    const boxes = screen.getAllByRole("checkbox");
    await userEvent.click(boxes[1]); // the send_email tool
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("greys out unavailable connectors", () => {
    render(<ToolPicker connectors={CONNECTORS} value={[]} onChange={vi.fn()} />);
    screen.getByText("Not available yet");
    const fax = screen.getByRole("checkbox", { name: /^FAX/ });
    expect(isDisabled(fax)).toBe(true);
  });

  it("an unavailable connector that's already selected can still be removed", async () => {
    const onChange = vi.fn();
    render(
      <ToolPicker
        connectors={CONNECTORS}
        value={[{ connector: "fax", tools: ["fax.send_fax"] }]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /^FAX/ }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("read-only shows only the selected connectors and tools", () => {
    render(
      <ToolPicker
        connectors={CONNECTORS}
        value={[{ connector: "gmail", tools: ["gmail.send_email"] }]}
        readOnly
      />,
    );
    expect(screen.queryByText("FAX")).toBeNull();
    screen.getByText("send_email");
    expect(screen.queryByText("read_thread")).toBeNull();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });
});
