import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ArrowRightIcon, FlagIcon, RotateCwIcon } from "lucide-react";
import { useState } from "react";

import {
  conversationActionMutation,
  listRunAttentionOptions,
  listSubjectsOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { ConversationOut, MessageOut } from "@/api/generated/types.gen";
import { SearchInput } from "@/components/shared/search-input";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AttentionCard } from "@/features/runs/attention-card";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

type Block = Record<string, unknown> & { type?: string };
type Option = { subject_id: string; title: string; kind?: string };
type Suggestion = { handle: string; reason?: string };

/** The cards inside a message (DATA_MODEL §4.2). Unknown types render nothing. */
export function MessageBlocks({
  conversation,
  message,
}: {
  conversation: ConversationOut;
  message: MessageOut;
}) {
  const blocks = (message.blocks ?? []) as Block[];
  if (blocks.length === 0) return null;
  return (
    <div className="space-y-2">
      {blocks.map((b, i) => (
        <OneBlock key={i} block={b} conversation={conversation} message={message} />
      ))}
    </div>
  );
}

function OneBlock({
  block,
  conversation,
  message,
}: {
  block: Block;
  conversation: ConversationOut;
  message: MessageOut;
}) {
  const navigate = useNavigate();
  // Pickers are open only while the chat still waits on this message (R4).
  const open = (conversation.pending as { message_id?: string } | null)?.message_id === message.id;
  const act = useApiMutation(conversationActionMutation(), { stale: STALE.conversation });
  const send = (
    type: "subject_pick" | "agent_suggest" | "clarify_agent" | "retry",
    value?: string,
  ) =>
    act.mutate({
      path: { conversation_id: conversation.id },
      body: { type, value: value ?? null, message_id: message.id },
    });

  switch (block.type) {
    case "subject_picker":
      return open ? (
        <SubjectPicker
          firmId={conversation.firm_id}
          options={(block.options as Option[]) ?? []}
          allowNone={block.allow_none !== false}
          disabled={act.isPending}
          onPick={(id) => send("subject_pick", id)}
        />
      ) : (
        <Card>
          <p className="text-muted-foreground text-sm">
            {conversation.subject_title ? `Picked: ${conversation.subject_title}` : "Answered"}
          </p>
        </Card>
      );
    case "agent_suggestion": {
      const suggested = (block.suggested as Suggestion[]) ?? [];
      return (
        <Card>
          <div className="flex flex-wrap gap-2">
            {suggested.map((s) => (
              <Tooltip key={s.handle}>
                <TooltipTrigger
                  render={
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!open || act.isPending}
                      onClick={() =>
                        send(block.mentioned ? "agent_suggest" : "clarify_agent", s.handle)
                      }
                    />
                  }
                >
                  Use @{s.handle}
                </TooltipTrigger>
                {s.reason && <TooltipContent>{s.reason}</TooltipContent>}
              </Tooltip>
            ))}
          </div>
          {!open && <p className="text-muted-foreground mt-2 text-xs">Answered</p>}
        </Card>
      );
    }
    case "finding":
      return <FindingTag urgency={block.urgency} />;
    case "attention":
    case "run_confirm":
      // findings were once posted as attention blocks: they are read, not answered
      return block.kind === "finding" ? (
        <FindingTag urgency={block.urgency} />
      ) : (
        <AttentionBlock block={block} message={message} />
      );
    case "run_link":
      return (
        <button
          type="button"
          onClick={() =>
            void navigate({
              to: ".",
              search: (prev) => ({ ...prev, drawer: block.run_id as string }),
            })
          }
          className="bg-card hover:border-foreground/20 flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm"
        >
          <span className="font-medium">@{String(block.agent ?? "agent")}</span>
          <span className="text-muted-foreground">· open the run</span>
          <ArrowRightIcon className="text-muted-foreground ml-auto size-4" />
        </button>
      );
    case "retry":
      return (
        <Card>
          <div className="flex items-center gap-3">
            <p className="text-sm">Couldn't process this message.</p>
            <Button
              size="sm"
              variant="outline"
              disabled={act.isPending}
              onClick={() => send("retry")}
            >
              <RotateCwIcon /> Retry
            </Button>
          </div>
        </Card>
      );
    default:
      return null;
  }
}

/** A finding the agent reported to the firm: its text is the message; nothing to answer. */
function FindingTag({ urgency }: { urgency: unknown }) {
  return (
    <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
      <FlagIcon className="size-3.5" /> Reported to the firm
      {typeof urgency === "string" && ` · ${urgency}`}
    </p>
  );
}

/** Attention cards know their state only through the run (R3). */
function AttentionBlock({ block, message }: { block: Block; message: MessageOut }) {
  const items = useQuery({
    ...listRunAttentionOptions({ path: { run_id: message.run_id ?? "" } }),
    enabled: !!message.run_id,
  });
  const id = block.step_result_id as string;
  const known = items.data?.find((a) => a.id === id);
  const confirm = block.type === "run_confirm";
  const item = known ?? {
    id,
    kind: confirm ? "confirm_completion" : String(block.kind ?? "question"),
    summary: confirm ? "Is this run complete?" : message.body,
    options: confirm
      ? [
          { value: "confirm", label: "Confirm complete" },
          { value: "reopen", label: "Reopen" },
        ]
      : ((block.options as { value: string; label: string }[]) ?? []),
  };
  return <AttentionCard item={item} freeText={block.free_text === true} />;
}

function SubjectPicker({
  firmId,
  options,
  allowNone,
  disabled,
  onPick,
}: {
  firmId: string;
  options: Option[];
  allowNone: boolean;
  disabled: boolean;
  onPick: (subjectId: string) => void;
}) {
  const [q, setQ] = useState<string>();
  const found = useQuery({
    ...listSubjectsOptions({ path: { firm_id: firmId }, query: { q, limit: 5 } }),
    enabled: !!q,
  });
  return (
    <Card>
      <div className="flex flex-wrap gap-2">
        {options.slice(0, 3).map((o) => (
          <Button
            key={o.subject_id}
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => onPick(o.subject_id)}
          >
            {o.title}
            {o.kind && <span className="text-muted-foreground">· {o.kind}</span>}
          </Button>
        ))}
        {allowNone && (
          <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onPick("none")}>
            None of these
          </Button>
        )}
      </div>
      <div className="mt-3 space-y-1">
        <SearchInput
          label="Find another case"
          placeholder="Find another case"
          value={q}
          onCommit={setQ}
        />
        {(found.data?.items ?? []).map((s) => (
          <button
            key={s.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s.id)}
            className="hover:bg-muted block w-full rounded-md px-2 py-1.5 text-left text-sm"
          >
            {s.title} <span className="text-muted-foreground">· {s.external_ref ?? s.kind}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="bg-card rounded-xl border p-3">{children}</div>;
}
