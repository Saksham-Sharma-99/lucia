import { useEffect, useRef, useState } from "react";
import { useWatch, type Path, type PathValue, type UseFormReturn } from "react-hook-form";
import { toast } from "sonner";

import { draftAgentPrompt } from "@/api/generated/sdk.gen";
import type { Basic, DraftContext } from "@/api/generated/types.gen";

import type { AgentForm } from "../sections";
import { promptEvent } from "./draft";

type Options = {
  /** Read when a run starts: who the agent is, and what else is already set up. */
  basic: () => Basic;
  context: () => DraftContext;
  /** After each successful draft. */
  onDone?: () => void;
};

export type PromptDraft = ReturnType<typeof usePromptDraft>;

/**
 * Streams a drafted (empty prompt) or refined prompt into the form's prompt field. A failure
 * puts the old text back; after a success, `undo` does, until the person edits the draft.
 * Leaving the page stops the stream.
 */
export function usePromptDraft<T extends Pick<AgentForm, "config">>(
  form: UseFormReturn<T>,
  { basic, context, onDone }: Options,
) {
  // Any editor form with the config in it (the wizard's, amend's): one field path, typed once.
  const field = "config.system_prompt" as Path<T>;
  const current = (useWatch({ control: form.control, name: field }) as string | undefined) ?? "";
  const [streaming, setStreaming] = useState(false);
  // The last draft and the text it replaced; Undo applies only while the draft is untouched.
  const [last, setLast] = useState<{ drafted: string; before: string } | null>(null);
  const run = useRef<AbortController | null>(null);
  useEffect(() => () => run.current?.abort(), []);

  const set = (text: string) =>
    form.setValue(field, text as PathValue<T, Path<T>>, { shouldDirty: true });

  const start = async (instruction: string) => {
    if (run.current) return; // one run at a time
    const controller = (run.current = new AbortController());
    const before = form.getValues(field) as string;
    let text = "";
    let done: string | undefined;
    let failure: string | undefined;
    setStreaming(true);
    try {
      const { stream } = await draftAgentPrompt({
        body: { instruction, basic: basic(), current_prompt: before || null, context: context() },
        signal: controller.signal,
        sseMaxRetryAttempts: 1, // a draft costs a model call; never re-send it
      });
      for await (const data of stream) {
        const event = promptEvent.safeParse(data);
        if (!event.success) {
          failure = "The drafter sent something unexpected. Try again.";
          break;
        }
        if (event.data.type === "delta") set((text += event.data.text));
        else if (event.data.type === "done") done = event.data.prompt;
        else failure = event.data.message;
      }
    } catch {
      // A refused request (503, 422) or a dropped connection: no outcome, handled below.
    }
    run.current = null;
    if (controller.signal.aborted) return; // the page is gone
    setStreaming(false);
    if (done === undefined) {
      set(before);
      toast.error(failure ?? "Couldn't draft the prompt. Try again.");
      return;
    }
    set(done);
    setLast({ drafted: done, before });
    onDone?.();
  };

  const canUndo = last !== null && current === last.drafted;
  const undo = () => {
    if (!canUndo) return;
    set(last.before);
    setLast(null);
  };

  return {
    start,
    streaming,
    /** There is a prompt to refine (otherwise the wand writes one). */
    refine: current.trim() !== "",
    canUndo,
    undo,
  };
}
