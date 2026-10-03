import { useQuery } from "@tanstack/react-query";

import { listMessagesOptions } from "@/api/generated/@tanstack/react-query.gen";

const LIMIT = 100;

/**
 * A chat's newest messages, oldest first. The API pages oldest first, so for a long chat the
 * total from page 1 points at the last page, which is fetched too.
 */
export function useMessages(conversationId: string | undefined) {
  const path = { conversation_id: conversationId ?? "" };
  const first = useQuery({
    ...listMessagesOptions({ path, query: { page: 1, limit: LIMIT } }),
    enabled: !!conversationId,
  });
  const last = Math.max(1, Math.ceil((first.data?.total ?? 0) / LIMIT));
  const tail = useQuery({
    ...listMessagesOptions({ path, query: { page: last, limit: LIMIT } }),
    enabled: !!conversationId && last > 1,
  });
  const messages = last > 1 ? (tail.data?.items ?? []) : (first.data?.items ?? []);
  return { messages, isLoading: first.isLoading };
}
