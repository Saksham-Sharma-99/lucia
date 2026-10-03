import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { MessagesSquareIcon, SquarePenIcon } from "lucide-react";
import { useState } from "react";

import {
  listConversationsOptions,
  renameConversationMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { ConversationOut } from "@/api/generated/types.gen";
import { MoreButton } from "@/components/shared/more-button";
import { SearchInput } from "@/components/shared/search-input";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { FirmPicker } from "@/features/runs/firm-picker";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";
import { cn } from "@/lib/utils";

import { groupByAge } from "./model";

/** The firm's chats: pick a firm, start a new chat, search, rename (docs/ui-refs). */
export function ChatList({
  firmId,
  activeId,
  onFirm,
  onNew,
}: {
  firmId: string | undefined;
  activeId?: string;
  onFirm: (firmId: string) => void;
  onNew: () => void;
}) {
  const [q, setQ] = useState<string>();
  const chats = useQuery({
    ...listConversationsOptions({ path: { firm_id: firmId ?? "" }, query: { q, limit: 100 } }),
    enabled: !!firmId,
    placeholderData: keepPreviousData,
  });
  return (
    <nav aria-label="Chats" className="flex h-full min-h-0 flex-col gap-3 border-r px-3 py-4">
      <div className="flex items-center gap-2 px-1">
        <MessagesSquareIcon className="text-brass size-5" />
        <span className="text-lg font-semibold">Playground</span>
      </div>
      <FirmPicker value={firmId} onChange={onFirm} />
      <Button variant="outline" className="justify-start" onClick={onNew}>
        <SquarePenIcon /> New chat
      </Button>
      <SearchInput label="Search chats" placeholder="Search chats" value={q} onCommit={setQ} />
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
        {firmId && chats.isSuccess && chats.data.items.length === 0 && (
          <p className="text-muted-foreground px-2 py-4 text-sm">
            {q ? "No chats match." : "No chats yet. Ask an agent something to start one."}
          </p>
        )}
        {groupByAge(chats.data?.items ?? []).map((g) => (
          <div key={g.label} className="mt-3 first:mt-1">
            <p className="text-muted-foreground px-2 pb-1 text-[0.7rem] font-semibold tracking-wider uppercase">
              {g.label}
            </p>
            <ul>
              {g.items.map((c) => (
                <ChatRow key={c.id} chat={c} active={c.id === activeId} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}

function ChatRow({ chat, active }: { chat: ConversationOut; active: boolean }) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(chat.title ?? "");
  const rename = useApiMutation(renameConversationMutation(), {
    stale: STALE.conversation,
  });
  const label = chat.title ?? "New chat";
  if (renaming)
    return (
      <li className="px-1 py-0.5">
        <Input
          autoFocus
          aria-label="Chat title"
          value={title}
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => setRenaming(false)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setRenaming(false);
            if (e.key === "Enter" && title.trim()) {
              rename.mutate({ path: { conversation_id: chat.id }, body: { title: title.trim() } });
              setRenaming(false);
            }
          }}
        />
      </li>
    );
  return (
    <li className="group relative">
      <Link
        to="/playground/$conversationId"
        params={{ conversationId: chat.id }}
        search={(prev) => ({ firm: prev.firm })}
        className={cn(
          "block rounded-md px-2 py-1.5 pr-8 text-sm",
          active ? "bg-muted font-medium" : "hover:bg-muted/60",
        )}
      >
        <span className="block truncate">{label}</span>
        {chat.subject_title && (
          <span className="text-muted-foreground block truncate text-xs">{chat.subject_title}</span>
        )}
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <MoreButton
              label={`Actions for ${label}`}
              className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-popup-open:opacity-100"
            />
          }
        />
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onClick={() => {
              setTitle(chat.title ?? "");
              setRenaming(true);
            }}
          >
            Rename
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}
