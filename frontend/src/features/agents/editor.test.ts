import { describe, expect, it } from "vitest";

import { VERSION_CONFIG } from "@/test/fixtures";

import { toForm } from "./config";
import { changedSections, sectionFor } from "./editor";

describe("sectionFor", () => {
  it.each([
    ["handle", "basic"],
    ["use_cases.3", "basic"],
    ["config.capabilities.1.tools.0", "capabilities"],
    ["config.models.loop", "prompt"],
    ["config.system_prompt", "prompt"],
    ["config.policy_pack.2.params.n", "policies"],
    ["config.alert_policy.fixed_urgency", "policies"],
    ["config.follow_up.ladder.0.channel", "schedules"],
    ["config.max_turns_per_episode", "schedules"],
  ])("%s belongs to %s", (field, section) => expect(sectionFor(field)).toBe(section));

  it("doesn't match on a shared prefix or unknown paths", () => {
    expect(sectionFor("config.models_extra")).toBeUndefined();
    expect(sectionFor("changelog")).toBeUndefined();
    expect(sectionFor("")).toBeUndefined();
  });
});

describe("changedSections", () => {
  it("is empty for an unchanged config", () => {
    expect(changedSections(toForm(VERSION_CONFIG), toForm(VERSION_CONFIG)).size).toBe(0);
  });

  it("marks only the sections that differ", () => {
    const base = toForm(VERSION_CONFIG);
    const edited = toForm(VERSION_CONFIG);
    edited.system_prompt = "New prompt";
    edited.follow_up.ladder[0].wait_hours = 72;
    expect([...changedSections(base, edited)].sort()).toEqual(["prompt", "schedules"]);
  });
});
