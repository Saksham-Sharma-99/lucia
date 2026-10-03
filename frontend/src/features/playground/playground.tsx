import { useFirm } from "@/features/runs/use-firm";

import { ChatList } from "./chat-list";
import { Conversation } from "./conversation";

export type PlaygroundSearch = {
  firm?: string;
  /** The task drawer, opened over the chat for this run. */
  drawer?: string;
  /** The subject drawer is open (read only). */
  subject?: boolean;
};

/** Chat with the firm's agents: the chat list on the left, the conversation on the right. */
export function Playground({
  conversationId,
  search,
  onSearch,
  onOpen,
}: {
  conversationId?: string;
  search: PlaygroundSearch;
  onSearch: (patch: Partial<PlaygroundSearch>) => void;
  /** Go to a chat (after the first message creates it), or to a new one (`undefined`). */
  onOpen: (conversationId: string | undefined, firmId?: string) => void;
}) {
  const { firmId, setFirm } = useFirm(search.firm);
  return (
    <div className="grid h-full min-h-0 grid-cols-[300px_1fr]">
      <ChatList
        firmId={firmId}
        activeId={conversationId}
        onFirm={(id) => {
          setFirm(id);
          onOpen(undefined, id);
        }}
        onNew={() => onOpen(undefined, firmId)}
      />
      {firmId ? (
        <Conversation
          key={conversationId ?? "new"}
          firmId={firmId}
          conversationId={conversationId}
          search={search}
          onSearch={onSearch}
          onCreated={(id) => onOpen(id, firmId)}
        />
      ) : (
        <div />
      )}
    </div>
  );
}
