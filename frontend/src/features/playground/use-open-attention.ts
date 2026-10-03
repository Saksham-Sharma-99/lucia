import { useQueries } from "@tanstack/react-query";

import { listRunAttentionOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { MessageOut } from "@/api/generated/types.gen";

const ASKS = new Set(["attention", "run_confirm"]);

/** Whether an attention card in this chat is still open: it is answered on its card, not by a
 * chat message. A card the run's cached list doesn't know yet arrived after that fetch, so it
 * counts as open; answering refetches the list (the cards' queries), which unlocks the chat. */
export function useOpenAttention(messages: MessageOut[]): boolean {
  const asks = messages.flatMap((m) =>
    m.run_id
      ? m.blocks
          .filter((b) => ASKS.has(b.type as string) && b.step_result_id)
          .map((b) => ({ runId: m.run_id as string, itemId: b.step_result_id as string }))
      : [],
  );
  const runIds = [...new Set(asks.map((a) => a.runId))];
  return useQueries({
    queries: runIds.map((id) => listRunAttentionOptions({ path: { run_id: id } })),
    combine: (results) => {
      const status = new Map(results.flatMap((r) => (r.data ?? []).map((a) => [a.id, a.status])));
      return asks.some((a) => (status.get(a.itemId) ?? "open") === "open");
    },
  });
}
