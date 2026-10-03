import { useQueryClient } from "@tanstack/react-query";
import { CircleAlertIcon, CircleCheckIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { answerAttentionMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { StepResultOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { STALE, invalidate } from "@/lib/invalidate";
import { isProblem } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";
import { cn } from "@/lib/utils";

type Item = Pick<StepResultOut, "id" | "kind" | "summary" | "options"> &
  Partial<Pick<StepResultOut, "status" | "answer" | "urgency">>;

type Option = { value: string; label: string };

const STALE_ON_ANSWER = [...STALE.run, ...STALE.notification, ...STALE.conversation];

/**
 * Something only a person can resolve, answered in place (chat, run page, bell). Options are
 * buttons; a question also takes free text; "Reopen" on a finished run asks what's missing.
 */
export function AttentionCard({ item, freeText }: { item: Item; freeText?: boolean }) {
  const queryClient = useQueryClient();
  const [reopening, setReopening] = useState(false);
  const [text, setText] = useState("");
  const answer = useApiMutation(
    {
      ...answerAttentionMutation(),
      onError: (e) => {
        if (isProblem(e) && e.status === 409) {
          toast.info("Already answered");
          void invalidate(queryClient, ...STALE_ON_ANSWER);
        } else toast.error(isProblem(e) ? e.detail : "Couldn't send the answer");
      },
    },
    { stale: STALE_ON_ANSWER, error: false },
  );
  const send = (choice: string | null, body: string | null) =>
    answer.mutate({ path: { item_id: item.id }, body: { choice, text: body } });

  const open = (item.status ?? "open") === "open";
  const options = item.options as Option[];
  const label = (value: unknown) =>
    options.find((o) => o.value === value)?.label ?? (value as string | undefined);
  const takesText = freeText ?? item.kind === "question";
  const choices = options.filter((o) => o.value !== "reopen");
  const canReopen = options.some((o) => o.value === "reopen");

  return (
    <div
      className={cn(
        "bg-card space-y-3 rounded-lg border p-3 text-sm",
        open && item.urgency === "P0" && "border-destructive/50",
      )}
    >
      <p className="flex gap-2">
        {open ? (
          <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
        ) : (
          <CircleCheckIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        )}
        <span>{item.summary}</span>
      </p>
      {!open ? (
        <p className="text-muted-foreground">
          {item.status === "answered"
            ? `Answered: ${label(item.answer?.choice) ?? String(item.answer?.text ?? "")}`
            : "Closed"}
        </p>
      ) : (
        <>
          {(choices.length > 0 || canReopen) && (
            <div className="flex flex-wrap gap-2">
              {choices.map((o) => (
                <Button
                  key={o.value}
                  size="sm"
                  variant={o.value === "confirm" ? "default" : "outline"}
                  disabled={answer.isPending}
                  onClick={() => send(o.value, null)}
                >
                  {o.label}
                </Button>
              ))}
              {canReopen && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={answer.isPending}
                  onClick={() => setReopening(true)}
                >
                  Reopen…
                </Button>
              )}
            </div>
          )}
          {(takesText || reopening) && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                send(reopening ? "reopen" : null, text.trim());
              }}
            >
              <Label htmlFor={`answer-${item.id}`} className="sr-only">
                {reopening ? "What's still needed?" : "Your answer"}
              </Label>
              <Textarea
                id={`answer-${item.id}`}
                rows={2}
                value={text}
                placeholder={reopening ? "What's still needed?" : "Type an answer"}
                onChange={(e) => setText(e.target.value)}
              />
              <Button size="sm" type="submit" disabled={!text.trim() || answer.isPending}>
                Send
              </Button>
            </form>
          )}
        </>
      )}
    </div>
  );
}
