import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { VersionConfig } from "@/api/generated/types.gen";
import { CONNECTORS, VERSION_CONFIG, connector, rule, tool } from "@/test/fixtures";

import { toForm } from "./config";
import { OrchestrationDiagram } from "./orchestration-diagram";

const REGISTRY = {
  connectors: [
    ...CONNECTORS,
    connector("slack", [
      tool("slack.listen_mention", {
        direction: "inbound",
        risk_tier: "read",
        display_name: "Listen to @mentions",
      }),
      tool("slack.send_message", { direction: "outbound", display_name: "Send message" }),
      ...[
        "slack.read_thread",
        "slack.list_channels",
        "slack.search_messages",
        "slack.get_user",
      ].map((name) => tool(name, { direction: "inbound", risk_tier: "read" })),
    ]),
  ],
  rules: [
    rule("recipient_must_be_contact", {}),
    { ...rule("quiet_hours", {}), display_name: "Quiet hours" },
  ],
};

const draw = (over: Partial<VersionConfig> = {}) =>
  render(
    <OrchestrationDiagram
      handle="records"
      config={toForm({ ...VERSION_CONFIG, ...over })}
      registry={REGISTRY}
    />,
  );

describe("OrchestrationDiagram", () => {
  it("reads as a loop: what wakes it, the agent, the policy check, what it produces", () => {
    draw({
      capabilities: [
        { connector: "gmail", tools: ["gmail.send_email", "gmail.read_thread"] },
        { connector: "slack", tools: ["slack.listen_mention", "slack.send_message"] },
      ],
      policy_pack: [{ rule: "quiet_hours", params: {} }],
      recurrence: { every_days: 14 },
    });
    screen.getByRole("img", { name: "How @records works" });
    // triggers: events, the follow-up schedule step by step, and the repeat
    screen.getByText("Listen to @mentions");
    screen.getByText("an @mention in Slack");
    screen.getByText("after 2d: email, up to 2×");
    screen.getByText("then escalate (P1 alert)");
    screen.getByText("Every 14 days");
    // tools and models are chips, each after its label
    const chip = (text: string) => screen.getByText(text).closest("g")!.querySelector("rect");
    expect(chip("slack.listen_mention")).not.toBeNull();
    // the agent, with its model and what it can read on demand
    screen.getByText("@records");
    screen.getByText("thinks with");
    expect(chip("m-big")).not.toBeNull();
    screen.getByText("can read");
    expect(chip("gmail.read_thread")).not.toBeNull();
    // the policy check names its rules and the guardrail model
    screen.getByText("Policy check, before every send");
    screen.getByText("guardrail model");
    expect(chip("m-small")).not.toBeNull();
    screen.getByText("Quiet hours");
    // what it produces, with the tool that does it
    screen.getByText("Emails sent");
    expect(chip("gmail.send_email")).not.toBeNull();
    screen.getByText("Slack replies");
    expect(chip("slack.send_message")).not.toBeNull();
    // guided arrows
    for (const text of [
      "wakes the agent",
      "decides on an action",
      "if every rule allows it",
      "then waits for the next trigger",
      "breaks the loop",
    ])
      screen.getByText(text);
  });

  it("shows when it breaks out of the loop: asking a person, or stopping", () => {
    draw({
      hitl: { ask_on: ["missing_contact"], verify_evidence_below: 0.75 },
      end_conditions: { max_duration_days: 30, max_steps: 200, on_subject_closed: "pause" },
    });
    screen.getByText("Asks a person");
    screen.getByText("when missing contact");
    // long lines wrap inside their box rather than being cut off
    screen.getByText(/^when unsure of a result/);
    screen.getByText(/75% confident\)$/);
    screen.getByText("Stops");
    screen.getByText(/^when the matter closes/);
    screen.getByText(/pauses$/);
    screen.getByText("after 30 days");
    screen.getByText("after 200 steps");
  });

  it("chips that don't fit on one row wrap onto the next, inside the box", () => {
    draw({
      capabilities: [
        {
          connector: "slack",
          tools: [
            "slack.read_thread",
            "slack.list_channels",
            "slack.search_messages",
            "slack.get_user",
          ],
        },
      ],
    });
    const box = screen.getByText("@records").closest("g")!;
    const frame = box.querySelector("rect")!;
    const bottom = Number(frame.getAttribute("y")) + Number(frame.getAttribute("height"));
    const right = Number(frame.getAttribute("x")) + Number(frame.getAttribute("width"));
    const chips = [...box.querySelectorAll(":scope g > rect")];
    const rows = new Set(chips.map((c) => c.getAttribute("y")));
    expect(rows.size).toBeGreaterThan(2); // the model row, plus the read tools over 2+ rows
    for (const c of chips) {
      expect(Number(c.getAttribute("y")) + Number(c.getAttribute("height"))).toBeLessThan(bottom);
      expect(Number(c.getAttribute("x")) + Number(c.getAttribute("width"))).toBeLessThanOrEqual(
        right,
      );
    }
  });

  it("an empty policy pack shows a placeholder, not a missing box", () => {
    draw({ policy_pack: [] });
    screen.getByText("Policy check, before every send");
    screen.getByText("No policy rules yet: add them on the Policies tab");
  });

  it("an agent nothing wakes says it is started by hand", () => {
    draw({
      capabilities: [{ connector: "gmail", tools: ["gmail.send_email"] }],
      follow_up: { mode: "none" },
    });
    screen.getByText("Started by hand");
    expect(screen.queryByText("Follow-up schedule")).toBeNull();
  });

  it("an agent-timed follow-up lists its window, channels and escalation", () => {
    draw({
      follow_up: {
        mode: "dynamic",
        dynamic: {
          min_hours: 24,
          max_hours: 72,
          business_hours: true,
          channels: ["email", "voice"],
          escalate_after: { attempts: 3, urgency: "P0" },
        },
      },
    });
    screen.getByText("Follow-up, timed by the agent");
    screen.getByText("every 1d–3d");
    screen.getByText("by email or a call");
    screen.getByText("escalates after 3 tries (P0)");
  });
});
