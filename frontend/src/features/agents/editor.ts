import { useQuery } from "@tanstack/react-query";
import type { FieldPath } from "react-hook-form";
import { z } from "zod";

import { validateAgentConfig } from "@/api/generated/sdk.gen";
import type { FieldError } from "@/api/generated/types.gen";
import { useDebounced } from "@/hooks/use-debounced";
import { isProblem } from "@/lib/problem";

import { configSchema, handleSchema, toPayload, type ConfigForm } from "./config";
import type { AgentForm } from "./sections";

export const agentFormSchema = z.object({
  handle: handleSchema,
  name: z.string().trim().min(1, "Name the agent").max(120),
  description: z.string().max(2000),
  use_cases: z.array(z.string()).max(20),
  config: configSchema,
  changelog: z.string().max(2000),
});

export const AGENT_TABS = [
  "overview",
  "prompt",
  "capabilities",
  "policies",
  "schedules",
  "evals",
  "versions",
] as const;
export type AgentTab = (typeof AGENT_TABS)[number];

/** The editing sections, in wizard order. Each owns some top-level form fields. */
export const SECTIONS = [
  { id: "basic", label: "Basic info", fields: ["handle", "name", "description", "use_cases"] },
  { id: "prompt", label: "Prompt and models", fields: ["config.system_prompt", "config.models"] },
  { id: "capabilities", label: "Capabilities", fields: ["config.capabilities"] },
  {
    id: "policies",
    label: "Policies and alerts",
    fields: ["config.policy_pack", "config.hitl", "config.alert_policy"],
  },
  {
    id: "schedules",
    label: "Schedules",
    fields: [
      "config.follow_up",
      "config.recurrence",
      "config.end_conditions",
      "config.max_turns_per_episode",
    ],
  },
] as const satisfies readonly {
  id: string;
  label: string;
  fields: readonly FieldPath<AgentForm>[];
}[];
export type SectionId = (typeof SECTIONS)[number]["id"];

/** Which section owns a field path like `config.follow_up.ladder.0.channel`. */
export function sectionFor(field: string): SectionId | undefined {
  return SECTIONS.find((s) => s.fields.some((f) => field === f || field.startsWith(`${f}.`)))?.id;
}

export type ServerCheck = { state: "idle" | "checking" | "ok" | "invalid"; errors: FieldError[] };

/**
 * Asks the server to validate the config 500 ms after the last edit. The server knows the
 * registry and the allowed models, so it catches what the client schema cannot.
 */
export function useServerValidation(config: ConfigForm, enabled = true): ServerCheck {
  const current = JSON.stringify(config);
  const debounced = useDebounced(current, 500);
  const check = useQuery({
    queryKey: ["validateAgentConfig", debounced],
    queryFn: async (): Promise<FieldError[]> => {
      try {
        await validateAgentConfig({
          body: { config: toPayload(JSON.parse(debounced) as ConfigForm) },
          throwOnError: true,
        });
        return [];
      } catch (e) {
        if (isProblem(e) && e.status === 422) return e.errors ?? [];
        throw e;
      }
    },
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  if (!enabled || check.isError) return { state: "idle", errors: [] };
  if (current !== debounced || check.isFetching || !check.data)
    return { state: "checking", errors: [] };
  return check.data.length ? { state: "invalid", errors: check.data } : { state: "ok", errors: [] };
}

export type AmendSection = Exclude<SectionId, "basic">;
export const AMEND_SECTIONS = SECTIONS.filter(
  (s): s is (typeof SECTIONS)[number] & { id: AmendSection } => s.id !== "basic",
);

/** Sections whose values differ from the base version. */
export function changedSections(base: ConfigForm, current: ConfigForm): Set<AmendSection> {
  const pick = (cfg: ConfigForm, fields: readonly string[]) =>
    JSON.stringify(
      fields.map((f) =>
        f
          .split(".")
          .slice(1)
          .reduce<unknown>((o, k) => (o as Record<string, unknown>)?.[k], cfg),
      ),
    );
  return new Set(
    AMEND_SECTIONS.filter((s) => pick(base, s.fields) !== pick(current, s.fields)).map((s) => s.id),
  );
}
