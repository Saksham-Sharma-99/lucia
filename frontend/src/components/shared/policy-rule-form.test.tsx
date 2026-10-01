import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { isDisabled } from "@/test/dom";
import { rule } from "@/test/fixtures";

import { PolicyRuleForm } from "./policy-rule-form";

/** PolicyRuleForm is controlled; keep its value in state like a real parent would. */
function Stateful(
  props: Omit<ComponentProps<typeof PolicyRuleForm>, "value"> & {
    initial: ComponentProps<typeof PolicyRuleForm>["value"];
  },
) {
  const [value, setValue] = useState(props.initial);
  return (
    <PolicyRuleForm
      {...props}
      value={value}
      onChange={(v) => {
        setValue(v);
        props.onChange(v);
      }}
    />
  );
}

const RULES = [
  rule("recipient_must_be_contact", { type: "object", properties: {} }),
  rule("per_subject_contact_cap", {
    type: "object",
    required: ["n"],
    properties: { n: { type: "integer", minimum: 1, maximum: 20 } },
  }),
  rule("attachment_allowed", {
    type: "object",
    additionalProperties: { type: "array", items: { enum: ["client", "provider"] } },
  }),
];

describe("PolicyRuleForm", () => {
  it("turning a rule on adds it with default params, in registry order", async () => {
    const onChange = vi.fn();
    render(
      <PolicyRuleForm
        rules={RULES}
        value={[{ rule: "recipient_must_be_contact", params: {} }]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("switch", { name: "Use per_subject_contact_cap" }));
    expect(onChange).toHaveBeenLastCalledWith([
      { rule: "recipient_must_be_contact", params: {} },
      { rule: "per_subject_contact_cap", params: { n: 1 } },
    ]);
  });

  it("turning a rule off removes it", async () => {
    const onChange = vi.fn();
    render(
      <PolicyRuleForm
        rules={RULES}
        value={[{ rule: "per_subject_contact_cap", params: { n: 3 } }]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("switch", { name: "Use per_subject_contact_cap" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("edits params and shows field errors at their path", async () => {
    const onChange = vi.fn();
    render(
      <Stateful
        rules={RULES}
        initial={[{ rule: "per_subject_contact_cap", params: { n: 3 } }]}
        onChange={onChange}
        errorFor={(path) => (path === "0.params.n" ? "Must be at most 20" : undefined)}
      />,
    );
    const input = screen.getByRole("spinbutton");
    await userEvent.clear(input);
    await userEvent.type(input, "5");
    expect(onChange).toHaveBeenLastCalledWith([
      { rule: "per_subject_contact_cap", params: { n: 5 } },
    ]);
    screen.getByText("Must be at most 20");
  });

  it("edits map-style params (document kind -> roles)", async () => {
    const onChange = vi.fn();
    render(
      <PolicyRuleForm
        rules={RULES}
        value={[{ rule: "attachment_allowed", params: {} }]}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText(/Document kind/), "hipaa_auth");
    await userEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(onChange).toHaveBeenLastCalledWith([
      { rule: "attachment_allowed", params: { hipaa_auth: [] } },
    ]);
  });

  it("map rows: a taken key can't be added twice, any other can (even `constructor`), rows remove", async () => {
    render(
      <Stateful
        rules={RULES}
        initial={[{ rule: "attachment_allowed", params: { hipaa_auth: ["client"] } }]}
        onChange={vi.fn()}
      />,
    );
    const box = screen.getByPlaceholderText(/Document kind/);
    const add = screen.getByRole("button", { name: /Add/ });
    await userEvent.type(box, "hipaa_auth");
    expect(isDisabled(add)).toBe(true);
    await userEvent.clear(box);
    await userEvent.type(box, "constructor");
    expect(isDisabled(add)).toBe(false);
    await userEvent.click(add);
    screen.getByText("constructor");
    await userEvent.click(screen.getByRole("button", { name: "Remove hipaa_auth" }));
    expect(screen.queryByText("hipaa_auth")).toBeNull();
  });

  it("hides unavailable rules unless they are already on, and locks when disabled", () => {
    const retired = { ...rule("old_rule", { type: "object", properties: {} }), available: false };
    render(<PolicyRuleForm rules={[...RULES, retired]} value={[]} onChange={vi.fn()} disabled />);
    expect(screen.queryByText("old_rule")).toBeNull();
    expect(screen.getAllByRole("switch").every(isDisabled)).toBe(true);
  });
});
