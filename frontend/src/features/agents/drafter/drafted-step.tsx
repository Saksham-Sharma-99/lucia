import { SparklesIcon, XIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { isDraftSection } from "./draft";
import type { WizardDrafter } from "./use-wizard-drafter";

/**
 * A wizard step as the drafter sees it: a skeleton while the AI drafts it, then the step with a
 * dismissible note on why it was set up this way and what couldn't be (never saved).
 */
export function DraftedStep({
  drafter,
  step,
  children,
}: {
  drafter: WizardDrafter;
  step: string;
  children: ReactNode;
}) {
  if (!isDraftSection(step)) return children;
  if (drafter.drafting === step)
    return (
      <div role="status" className="space-y-4">
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <SparklesIcon className="size-4 animate-pulse" /> Drafting from your prompt…
        </p>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  const note = drafter.notes[step];
  return (
    <>
      {note && (
        <Alert className="mb-6">
          <SparklesIcon />
          <AlertTitle>Drafted from your prompt</AlertTitle>
          <AlertDescription>
            <p>{note.rationale}</p>
            {note.unmapped.length > 0 && (
              <p className="mt-1">Couldn&apos;t set up: {note.unmapped.join("; ")}</p>
            )}
          </AlertDescription>
          <AlertAction>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Dismiss note"
              onClick={() => drafter.dismiss(step)}
            >
              <XIcon />
            </Button>
          </AlertAction>
        </Alert>
      )}
      {children}
    </>
  );
}
