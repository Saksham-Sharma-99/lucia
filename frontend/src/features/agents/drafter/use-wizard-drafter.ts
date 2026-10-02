import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { UseFormReturn } from "react-hook-form";

import { draftAgentSectionMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { Registry } from "@/features/registry/use-registry";
import { toastError } from "@/lib/problem";

import { blankConfig } from "../config";
import { changedSections } from "../editor";
import type { AgentForm } from "../sections";
import {
  DRAFT_SECTIONS,
  draftContext,
  isDraftSection,
  upstreamOf,
  withDraft,
  type DraftNote,
  type DraftSection,
} from "./draft";
import { usePromptDraft } from "./use-prompt-draft";

export type WizardDrafter = ReturnType<typeof useWizardDrafter>;

/**
 * The New agent wizard's AI drafting. The wand writes the prompt; once it has, each later step
 * is drafted the first time it's reached (`reach`), from the prompt, basic info and the person's
 * current values for the steps before it. A step is tried once, and a step reached before the
 * wand was used is left alone. A failure leaves the step as it was.
 */
export function useWizardDrafter(form: UseFormReturn<AgentForm>, registry: Registry) {
  const [wandUsed, setWandUsed] = useState(false);
  // Steps already reached (drafted or not): a step the person has seen is never drafted over.
  // A ref, as it's not rendered, and it also stops a double click from drafting twice.
  const reached = useRef(new Set<DraftSection>());
  const [notes, setNotes] = useState<Partial<Record<DraftSection, DraftNote>>>({});
  const section = useMutation({
    ...draftAgentSectionMutation(),
    onError: (e) => toastError(e, "Couldn't draft this step"),
  });
  const basic = () => {
    const { name, description, use_cases } = form.getValues();
    return { name, description, use_cases };
  };

  const prompt = usePromptDraft(form, {
    basic,
    // Refine sees only steps the person has set up; untouched defaults would mislead it.
    context: () => {
      const config = form.getValues("config");
      const changed = changedSections(blankConfig(registry.models), config);
      return draftContext(
        config,
        DRAFT_SECTIONS.filter((s) => changed.has(s)),
      );
    },
    onDone: () => setWandUsed(true),
  });

  // Call on every forward move (Next). Other navigation only returns to steps already reached.
  const reach = (step: string) => {
    if (!isDraftSection(step) || reached.current.has(step)) return;
    reached.current.add(step);
    if (!wandUsed) return;
    const config = form.getValues("config");
    section.mutate(
      {
        body: {
          section: step,
          system_prompt: config.system_prompt,
          basic: basic(),
          upstream: draftContext(config, upstreamOf(step)),
        },
      },
      {
        onSuccess: (draft) => {
          form.setValue("config", withDraft(form.getValues("config"), step, draft), {
            shouldDirty: true,
          });
          setNotes((n) => ({
            ...n,
            [step]: { rationale: draft.rationale, unmapped: draft.unmapped },
          }));
        },
      },
    );
  };

  const drafting = section.isPending ? section.variables.body.section : undefined;
  return {
    prompt,
    reach,
    /** The step being drafted right now, if any. */
    drafting,
    notes,
    dismiss: (step: DraftSection) => setNotes((n) => ({ ...n, [step]: undefined })),
    /** Navigation waits while the AI writes. */
    busy: prompt.streaming || drafting !== undefined,
  };
}
