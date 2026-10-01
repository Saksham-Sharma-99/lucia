import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { VERSION_CONFIG } from "@/test/fixtures";

import { toForm, type ConfigForm } from "./config";
import { LadderEditor } from "./ladder-editor";

type Ladder = ConfigForm["follow_up"]["ladder"];
const ladder = (): Ladder => JSON.parse(screen.getByTestId("ladder").textContent ?? "[]");

function Harness({
  channels = [{ value: "email", label: "Email" }],
}: {
  channels?: { value: string; label: string }[];
}) {
  const form = useForm<{ config: ConfigForm }>({
    defaultValues: { config: toForm(VERSION_CONFIG) },
  });
  const rungs = useWatch({ control: form.control, name: "config.follow_up.ladder" });
  return (
    <FormProvider {...form}>
      <LadderEditor channels={channels} />
      <output data-testid="ladder">{JSON.stringify(rungs)}</output>
    </FormProvider>
  );
}

describe("LadderEditor", () => {
  it("adds a contact step on the first allowed channel", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Add step" }));
    expect(ladder()).toHaveLength(3);
    expect(ladder()[2]).toMatchObject({ kind: "channel", channel: "email", wait_hours: 72 });
  });

  it("reorders and removes steps", async () => {
    render(<Harness />);
    await userEvent.click(screen.getAllByRole("button", { name: "Move down" })[0]);
    expect(ladder().map((r) => r.kind)).toEqual(["action", "channel"]);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove step" })[0]);
    expect(ladder().map((r) => r.kind)).toEqual(["channel"]);
  });

  it("explains how to unlock contact steps when no channel is allowed", () => {
    render(<Harness channels={[]} />);
    screen.getByText(/Enable a send tool/);
  });

  it("shows the wait in days", () => {
    render(<Harness />);
    screen.getByText("h · 2d");
  });
});

describe("LadderEditor typing", () => {
  it("keeps focus and every digit while typing a wait", async () => {
    render(<Harness />);
    const wait = screen.getAllByLabelText("Wait in hours")[0];
    await userEvent.clear(wait);
    await userEvent.type(wait, "120");
    expect(document.activeElement).toBe(wait);
    expect(ladder()[0].wait_hours).toBe(120);
    screen.getByText("h · 5d");
  });

  it("switches a contact step to an escalation with a default urgency", async () => {
    render(<Harness />);
    await userEvent.click(screen.getAllByRole("combobox")[0]);
    await userEvent.click(await screen.findByRole("option", { name: "Flag for review" }));
    expect(ladder()[0]).toMatchObject({
      kind: "action",
      action: "flag",
      channel: null,
      urgency: "P1",
    });
  });
});
