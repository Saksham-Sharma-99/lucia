import { describe, expect, it } from "vitest";

import { blankConfig, toForm } from "../config";
import { VERSION_CONFIG } from "@/test/fixtures";

import { DRAFT_SECTIONS, draftContext, upstreamOf, withDraft } from "./draft";

const NOTE = { rationale: "why", unmapped: [] };
const config = () => toForm(VERSION_CONFIG);

describe("drafter context", () => {
  it("each section is drafted from the ones before it", () => {
    expect(DRAFT_SECTIONS.map(upstreamOf)).toEqual([
      [],
      ["capabilities"],
      ["capabilities", "policies"],
    ]);
  });

  it("sends only the asked sections, in API shape", () => {
    expect(draftContext(config(), [])).toEqual({});
    expect(draftContext(config(), ["capabilities"])).toEqual({
      capabilities: VERSION_CONFIG.capabilities,
    });
    const all = draftContext(config(), DRAFT_SECTIONS);
    expect(Object.keys(all).sort()).toEqual(
      [
        "alert_policy",
        "capabilities",
        "end_conditions",
        "follow_up",
        "hitl",
        "max_turns_per_episode",
        "policy_pack",
        "recurrence",
      ].sort(),
    );
    // The payload form: a fixed ladder carries no dynamic settings.
    expect(all.follow_up).toMatchObject({ mode: "fixed_ladder", dynamic: null });
  });
});

describe("applying a draft", () => {
  it("replaces only the drafted section", () => {
    const before = { ...config(), system_prompt: "Mine." };
    const after = withDraft(before, "capabilities", {
      section: "capabilities",
      capabilities: [{ connector: "vapi", tools: ["vapi.place_call"] }],
      ...NOTE,
    });
    expect(after.capabilities).toEqual([{ connector: "vapi", tools: ["vapi.place_call"] }]);
    expect({ ...after, capabilities: before.capabilities }).toEqual(before);
  });

  it("fills a policies draft into the form shape", () => {
    const after = withDraft(blankConfig(["m"]), "policies", {
      section: "policies",
      policy_pack: [{ rule: "recipient_must_be_contact" }],
      hitl: { ask_on: ["legal_question"] },
      alert_policy: {
        urgency_mode: "fixed",
        fixed_urgency: "P0",
        default_channels: { P0: ["email"] },
      },
      ...NOTE,
    });
    expect(after.policy_pack).toEqual([{ rule: "recipient_must_be_contact", params: {} }]);
    expect(after.hitl).toEqual({ ask_on: ["legal_question"], verify_evidence_below: 0.8 });
    expect(after.alert_policy).toEqual({
      urgency_mode: "fixed",
      fixed_urgency: "P0",
      default_channels: { P0: ["email"], P1: [], P2: [] },
    });
  });

  it("fills a schedules draft, including the turn limit, and keeps other modes' defaults", () => {
    const after = withDraft(blankConfig(["m"]), "schedules", {
      section: "schedules",
      follow_up: { mode: "fixed_ladder", ladder: [{ channel: "email", wait_hours: 48 }] },
      recurrence: { every_days: 14 },
      end_conditions: { max_duration_days: 730, max_steps: 2000, on_subject_closed: "pause" },
      max_turns_per_episode: 20,
      ...NOTE,
    });
    expect(after.follow_up.mode).toBe("fixed_ladder");
    expect(after.follow_up.ladder).toEqual([
      {
        kind: "channel",
        channel: "email",
        action: null,
        wait_hours: 48,
        attempts: 1,
        urgency: null,
      },
    ]);
    expect(after.follow_up.dynamic.min_hours).toBe(48); // the form's default, ready if switched
    expect(after.recurrence).toEqual({ every_days: 14 });
    expect(after.end_conditions.on_subject_closed).toBe("pause");
    expect(after.max_turns_per_episode).toBe(20);
  });
});
