import { z } from "zod";

import type {
  CapabilitiesDraft,
  DraftContext,
  PoliciesDraft,
  PromptDelta,
  PromptDone,
  PromptFailed,
  SchedulesDraft,
  SectionDraftRequest,
  VersionConfig,
} from "@/api/generated/types.gen";

import { toForm, toPayload, type ConfigForm } from "../config";
import { SECTIONS } from "../editor";

export type DraftSection = SectionDraftRequest["section"];
export type SectionDraft = CapabilitiesDraft | PoliciesDraft | SchedulesDraft;
export type DraftNote = Pick<SectionDraft, "rationale" | "unmapped">;

/**
 * One event of the prompt stream, checked at runtime: the generated client types stream items as
 * `unknown`. `satisfies` keeps it in step with the generated event types.
 */
export const promptEvent = z.discriminatedUnion("type", [
  z.object({ type: z.literal("delta"), text: z.string() }),
  z.object({ type: z.literal("done"), prompt: z.string() }),
  z.object({ type: z.literal("error"), code: z.string(), message: z.string() }),
]) satisfies z.ZodType<PromptDelta | PromptDone | PromptFailed>;

/** Every section after the prompt is drafted, in wizard order, from the ones before it. */
const DRAFTED = SECTIONS.filter(
  (s): s is Extract<(typeof SECTIONS)[number], { id: DraftSection }> =>
    s.id !== "basic" && s.id !== "prompt",
);
export const DRAFT_SECTIONS = DRAFTED.map((s) => s.id);

export const isDraftSection = (id: string): id is DraftSection =>
  DRAFT_SECTIONS.some((s) => s === id);

/**
 * The config keys a section owns, e.g. policies -> policy_pack, hitl, alert_policy. Every one is
 * also a drafter context key (draft.test.ts checks the full set).
 */
const ownedKeys = (section: DraftSection) =>
  DRAFTED.find((s) => s.id === section)!.fields.map(
    (f) => f.slice("config.".length) as keyof ConfigForm & keyof DraftContext,
  );

const pick = <T extends object>(from: T, keys: (keyof T)[]) =>
  Object.fromEntries(keys.map((k) => [k, from[k]])) as Partial<T>;

/** The person's current values for `sections`, in API shape, as drafter context. */
export function draftContext(config: ConfigForm, sections: readonly DraftSection[]): DraftContext {
  const payload = toPayload(config);
  return Object.fromEntries(sections.flatMap(ownedKeys).map((k) => [k, payload[k]]));
}

/** The sections a section is drafted from: the ones before it. */
export const upstreamOf = (section: DraftSection) =>
  DRAFT_SECTIONS.slice(0, DRAFT_SECTIONS.indexOf(section));

/**
 * `config` with the drafted section's fields replaced, every other section left as is. The draft
 * is in API shape, so it goes through the same `toForm` a stored version does.
 */
export function withDraft(
  config: ConfigForm,
  section: DraftSection,
  draft: SectionDraft,
): ConfigForm {
  const keys = ownedKeys(section);
  const drafted = toForm({ ...toPayload(config), ...pick(draft as Partial<VersionConfig>, keys) });
  return { ...config, ...pick(drafted, keys) };
}
