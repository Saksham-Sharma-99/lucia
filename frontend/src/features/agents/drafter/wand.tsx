import { Undo2Icon, WandSparklesIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import type { PromptDraft } from "./use-prompt-draft";

const MAX_INSTRUCTION = 4000;

/**
 * "Write with AI" (empty prompt) or "Refine with AI": a popover asking what to write or what to
 * change, plus Undo for the last run.
 */
export function Wand({
  draft,
  enabled,
  prefill,
}: {
  draft: PromptDraft;
  enabled: boolean;
  /** What the box starts with when writing from scratch. */
  prefill: string;
}) {
  const { refine } = draft;
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const text = instruction.trim();
  const submit = () => {
    if (!text) return;
    setOpen(false);
    void draft.start(text);
  };

  const trigger = (
    <Button variant="link" size="sm" disabled={!enabled || draft.streaming}>
      <WandSparklesIcon />
      {draft.streaming ? "Writing…" : refine ? "Refine with AI" : "Write with AI"}
    </Button>
  );
  return (
    <div className="flex items-center justify-end gap-1">
      {draft.canUndo && !draft.streaming && (
        <Button variant="link" size="sm" onClick={draft.undo}>
          <Undo2Icon /> Undo
        </Button>
      )}
      {enabled ? (
        <Popover
          open={open}
          onOpenChange={(o) => {
            setOpen(o);
            if (o) setInstruction(refine ? "" : prefill);
          }}
        >
          <PopoverTrigger render={trigger} />
          <PopoverContent align="end" className="w-96">
            <label htmlFor="wand-instruction" className="font-medium">
              {refine ? "What should change?" : "What kind of agent is this?"}
            </label>
            <Textarea
              id="wand-instruction"
              rows={5}
              maxLength={MAX_INSTRUCTION}
              value={instruction}
              placeholder={
                refine
                  ? "e.g. Shorter, and never leave voicemails"
                  : "e.g. Calls clients every two weeks to see how treatment is going"
              }
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
            />
            <div className="flex justify-end">
              <Button size="sm" disabled={!text} onClick={submit}>
                {refine ? "Refine" : "Write"}
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      ) : (
        <Tooltip>
          <TooltipTrigger render={<span tabIndex={0}>{trigger}</span>} />
          <TooltipContent>AI drafting isn&apos;t configured</TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
