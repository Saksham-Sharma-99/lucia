import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { conversationEvents } from "@/api/generated/sdk.gen";
import { invalidate } from "@/lib/invalidate";

/**
 * Live chat events (SSE). Every event refetches the messages; `conversation.updated` also the
 * chat, its runs and the chat list. `progress` says what the orchestrator is doing, until the
 * next other event. The generated client reconnects; a reconnect refetches too.
 */
export function useConversationEvents(conversationId: string | undefined) {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<string | null>(null);
  useEffect(() => {
    if (!conversationId) return;
    const controller = new AbortController();
    const refresh = (event?: string) => {
      void invalidate(queryClient, "listMessages");
      if (event === "conversation.updated")
        void invalidate(
          queryClient,
          "getConversation",
          "listConversationRuns",
          "listConversations",
        );
    };
    void (async () => {
      try {
        const { stream } = await conversationEvents({
          path: { conversation_id: conversationId },
          signal: controller.signal,
          onSseError: () => refresh(),
          onSseEvent: ({ event, data }) => {
            if (event === "progress") {
              setStage((data as { stage?: string } | undefined)?.stage ?? null);
              return;
            }
            setStage(null);
            refresh(event);
          },
        });
        // Events are handled in onSseEvent; draining the stream keeps the connection open.
        const reader = stream[Symbol.asyncIterator]();
        while (!(await reader.next()).done) {
          // drain
        }
      } catch {
        // aborted on unmount, or the server refused: the next mount retries
      }
    })();
    return () => controller.abort();
  }, [conversationId, queryClient]);
  return { stage };
}
