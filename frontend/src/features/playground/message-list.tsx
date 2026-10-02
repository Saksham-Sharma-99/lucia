import { SparklesIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import type { ConversationOut, MessageOut } from "@/api/generated/types.gen";
import { Markdown } from "@/components/shared/markdown";
import { PROGRESS_STAGES } from "@/features/runs/model";
import { cn } from "@/lib/utils";

import { MessageBlocks } from "./message-blocks";

/** The chat: people on the right, the orchestrator muted, agents with their handle. */
export function MessageList({
  conversation,
  messages,
  stage,
}: {
  conversation: ConversationOut;
  messages: MessageOut[];
  stage: string | null;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length, stage]);
  return (
    <ol className="mx-auto w-full max-w-3xl space-y-5 px-6 py-6">
      {messages.map((m) => (
        <li
          key={m.id}
          data-actor={m.actor}
          className={cn("flex flex-col gap-2", m.actor === "human" && "items-end")}
        >
          {m.actor === "human" ? (
            <div className="bg-primary/10 max-w-[80%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm whitespace-pre-wrap">
              {m.body}
            </div>
          ) : (
            <div className="flex max-w-[90%] gap-3">
              <span
                className={cn(
                  "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-[0.65rem] font-semibold",
                  m.actor === "agent" ? "bg-brass/15 text-brass" : "bg-muted text-muted-foreground",
                )}
                aria-hidden
              >
                {m.actor === "agent" ? "@" : <SparklesIcon className="size-3.5" />}
              </span>
              <div className="min-w-0 flex-1 space-y-2">
                {m.actor === "agent" && (
                  <p className="text-muted-foreground text-xs font-medium">
                    @{m.agent_handle ?? "agent"}
                  </p>
                )}
                {m.actor === "agent" ? (
                  <Markdown>{m.body}</Markdown>
                ) : (
                  <p className="text-muted-foreground text-sm whitespace-pre-wrap">{m.body}</p>
                )}
                <MessageBlocks conversation={conversation} message={m} />
              </div>
            </div>
          )}
        </li>
      ))}
      {stage && (
        <li className="text-muted-foreground flex items-center gap-2 text-sm" aria-live="polite">
          <span className="bg-primary size-2 animate-pulse rounded-full" />
          {PROGRESS_STAGES[stage] ?? "Working on it…"}
        </li>
      )}
      <div ref={end} />
    </ol>
  );
}
