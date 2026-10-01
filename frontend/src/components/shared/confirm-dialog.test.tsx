import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { isDisabled } from "@/test/dom";

import { ConfirmDialog } from "./confirm-dialog";

const show = (props: {
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onOpenChange?: (open: boolean) => void;
}) =>
  render(
    <ConfirmDialog
      open
      onOpenChange={() => {}}
      title="Archive @records?"
      description={
        <ul>
          <li>Acme Law (v1)</li>
        </ul>
      }
      confirmLabel="Archive"
      {...props}
    />,
  );

describe("ConfirmDialog", () => {
  it("confirms, and can hold a list in its description", async () => {
    const onConfirm = vi.fn();
    show({ onConfirm });
    screen.getByRole("listitem");
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("closes itself once confirmed", async () => {
    const onOpenChange = vi.fn();
    show({ onConfirm: vi.fn(), onOpenChange });
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("a disabled confirm can't be used", async () => {
    const onConfirm = vi.fn();
    show({ onConfirm, confirmDisabled: true });
    const button = screen.getByRole("button", { name: "Archive" });
    expect(isDisabled(button)).toBe(true);
    await userEvent.click(button);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
