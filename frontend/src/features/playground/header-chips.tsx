import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon, FolderIcon, PlayIcon } from "lucide-react";

import { listConversationRunsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { ConversationOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isTerminal, statusLabel } from "@/features/runs/model";

/** The chat's subject (opens its drawer) and the agent runs it started (open a run). */
export function HeaderChips({
  conversation,
  onSubject,
  onRun,
}: {
  conversation?: ConversationOut;
  onSubject: () => void;
  onRun: (runId: string) => void;
}) {
  const runs = useQuery({
    ...listConversationRunsOptions({ path: { conversation_id: conversation?.id ?? "" } }),
    enabled: !!conversation,
    // Statuses change as runs work; refresh while any can still change.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => !isTerminal(r.status)) ? 3000 : false,
  });
  if (!conversation) return null;
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" variant="outline" disabled={!conversation.subject_id} onClick={onSubject}>
        <FolderIcon /> {conversation.subject_title ?? "No case yet"}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button size="sm" variant="outline" disabled={(runs.data ?? []).length === 0} />}
        >
          <PlayIcon /> Agent runs <ChevronDownIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          {(runs.data ?? []).map((r) => (
            <DropdownMenuItem key={r.id} onClick={() => onRun(r.id)}>
              <span className="font-medium">@{r.agent_handle}</span>{" "}
              <span className="text-muted-foreground">
                · {statusLabel(r.status)} · {r.tasks_done}/{r.tasks_total} tasks done
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
