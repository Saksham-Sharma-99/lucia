import { useQuery } from "@tanstack/react-query";
import { SparklesIcon } from "lucide-react";
import { useState } from "react";

import {
  createConversationMutation,
  getConversationOptions,
  getMeOptions,
  getRunOptions,
  listMentionableAgentsOptions,
  sendMessageMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import { TaskDrawer } from "@/features/runs/task-drawer";
import { SubjectDrawer } from "@/features/subjects/subject-drawer";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { Composer } from "./composer";
import { HeaderChips } from "./header-chips";
import { MessageList } from "./message-list";
import type { PlaygroundSearch } from "./playground";
import { useConversationEvents } from "./use-conversation-events";
import { useMessages } from "./use-messages";
import { useOpenAttention } from "./use-open-attention";

/** One chat (or a new one): greeting and header chips, messages, composer, drawers. */
export function Conversation({
  firmId,
  conversationId,
  search,
  onSearch,
  onCreated,
}: {
  firmId: string;
  conversationId?: string;
  search: PlaygroundSearch;
  onSearch: (patch: Partial<PlaygroundSearch>) => void;
  onCreated: (conversationId: string) => void;
}) {
  const me = useQuery(getMeOptions());
  const conversation = useQuery({
    ...getConversationOptions({ path: { conversation_id: conversationId ?? "" } }),
    enabled: !!conversationId,
  });
  const { messages } = useMessages(conversationId);
  const { stage } = useConversationEvents(conversationId);
  const awaitingAnswer = useOpenAttention(messages);
  const [text, setText] = useState("");
  const create = useApiMutation(createConversationMutation(), { stale: STALE.conversation });
  const sendMessage = useApiMutation(sendMessageMutation(), { stale: STALE.conversation });
  const busy = create.isPending || sendMessage.isPending || !!stage;

  const send = async (body: string) => {
    let id = conversationId;
    if (!id) {
      id = (await create.mutateAsync({ path: { firm_id: firmId }, body: {} })).id;
    }
    await sendMessage.mutateAsync({ path: { conversation_id: id }, body: { body } });
    setText("");
    if (!conversationId) onCreated(id);
  };

  const c = conversation.data;
  return (
    <main
      aria-label="Conversation"
      className="relative flex h-full min-h-0 flex-col bg-[radial-gradient(ellipse_at_top_right,rgba(251,207,232,0.18),transparent_55%),radial-gradient(ellipse_at_bottom_left,rgba(191,219,254,0.18),transparent_55%)]"
    >
      <header className="flex items-center justify-between gap-3 border-b px-6 py-3">
        <h1 className="font-semibold">Hi, {me.data?.display_name ?? "there"}</h1>
        <HeaderChips
          conversation={c}
          onSubject={() => onSearch({ subject: true })}
          onRun={(runId) => onSearch({ drawer: runId })}
        />
      </header>
      {conversationId ? (
        <>
          {/* relative: absolutely positioned descendants (sr-only labels) stay clipped here
              instead of stretching the page, which made the whole layout scroll */}
          <div className="relative min-h-0 flex-1 overflow-y-auto">
            {c && <MessageList conversation={c} messages={messages} stage={stage} />}
          </div>
          <div className="mx-auto w-full max-w-3xl px-6 pb-5">
            {awaitingAnswer ? (
              // a question is answered on its card, not by a chat message
              <p className="text-muted-foreground rounded-2xl border border-dashed px-4 py-3 text-center text-sm">
                Answer the open question above to continue
              </p>
            ) : (
              <Composer
                firmId={firmId}
                disabled={busy}
                value={text}
                onChange={setText}
                onSend={(b) => void send(b).catch(() => {})}
              />
            )}
          </div>
        </>
      ) : (
        <EmptyChat
          firmId={firmId}
          text={text}
          setText={setText}
          busy={busy}
          onSend={(b) => void send(b).catch(() => {})}
        />
      )}
      {search.drawer && (
        <RunDrawer runId={search.drawer} onClose={() => onSearch({ drawer: undefined })} />
      )}
      {search.subject && c?.subject_id && (
        <SubjectDrawer
          firmId={firmId}
          subjectId={c.subject_id}
          readOnly
          onClose={() => onSearch({ subject: undefined })}
        />
      )}
    </main>
  );
}

function EmptyChat({
  firmId,
  text,
  setText,
  busy,
  onSend,
}: {
  firmId: string;
  text: string;
  setText: (t: string) => void;
  busy: boolean;
  onSend: (body: string) => void;
}) {
  const agents = useQuery(listMentionableAgentsOptions({ path: { firm_id: firmId } })).data ?? [];
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6">
      <h2 className="flex items-center gap-3 text-3xl font-semibold tracking-tight">
        <SparklesIcon className="text-brass size-8" /> What can I help you with?
      </h2>
      <div className="w-full max-w-2xl">
        <Composer
          firmId={firmId}
          disabled={busy}
          value={text}
          onChange={setText}
          onSend={onSend}
          autoFocus
        />
      </div>
      {agents.length > 0 && (
        <div className="flex max-w-2xl flex-wrap justify-center gap-2">
          {agents.map((a) => (
            <button
              key={a.handle}
              type="button"
              onClick={() => setText(`@${a.handle} ${text}`.trimEnd() + " ")}
              className="bg-card hover:border-foreground/20 rounded-full border px-3 py-1 text-sm"
            >
              @{a.handle} · {a.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** A run's task drawer over the chat (from a run link or the Agent runs menu). */
function RunDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const run = useQuery(getRunOptions({ path: { run_id: runId } }));
  const [taskId, setTaskId] = useState<string>("");
  if (!run.data) return null;
  return <TaskDrawer run={run.data} taskId={taskId} onTask={setTaskId} onClose={onClose} />;
}
