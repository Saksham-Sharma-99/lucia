import { useQuery } from "@tanstack/react-query";
import { ArrowUpIcon } from "lucide-react";
import { useRef, useState } from "react";

import { listMentionableAgentsOptions } from "@/api/generated/@tanstack/react-query.gen";
import { cn } from "@/lib/utils";

const MENTION = /(^|\s)@([a-z0-9_-]*)$/i;

/** The message box: Enter sends, Shift+Enter adds a line, `@` suggests the firm's agents. */
export function Composer({
  firmId,
  disabled,
  value,
  onChange,
  onSend,
  autoFocus,
}: {
  firmId: string;
  disabled?: boolean;
  value: string;
  onChange: (text: string) => void;
  onSend: (text: string) => void;
  autoFocus?: boolean;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [active, setActive] = useState(0);
  const agents = useQuery(listMentionableAgentsOptions({ path: { firm_id: firmId } })).data ?? [];
  const query = MENTION.exec(value)?.[2];
  const matches =
    query === undefined
      ? []
      : agents.filter((a) => a.handle.startsWith(query.toLowerCase())).slice(0, 6);
  const hasMention = agents.some((a) => new RegExp(`(^|\\s)@${a.handle}\\b`).test(value));

  const insert = (handle: string) => {
    onChange(value.replace(MENTION, (_, space: string) => `${space}@${handle} `));
    setActive(0);
    box.current?.focus();
  };
  const send = () => {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
  };

  return (
    <div className="relative">
      {matches.length > 0 && (
        <ul
          role="listbox"
          aria-label="Agents"
          className="bg-popover absolute bottom-full left-0 z-10 mb-2 w-80 overflow-hidden rounded-xl border p-1 shadow-lg"
        >
          {matches.map((a, i) => (
            <li
              key={a.handle}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                insert(a.handle);
              }}
              className={cn(
                "cursor-pointer rounded-lg px-3 py-2 text-sm",
                i === active && "bg-muted",
              )}
            >
              <span className="font-medium">@{a.handle}</span>{" "}
              <span className="text-muted-foreground">· {a.name}</span>
              <p className="text-muted-foreground truncate text-xs">{a.description}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="rounded-2xl bg-[linear-gradient(100deg,#f9a8d4,#fdba74,#93c5fd,#c4b5fd)] p-[1.5px] shadow-sm">
        <div className="bg-background flex items-end gap-2 rounded-[calc(1rem-1.5px)] px-4 py-3">
          <textarea
            ref={box}
            aria-label="Message"
            autoFocus={autoFocus}
            rows={2}
            value={value}
            placeholder="Ask anything… (@ to mention an agent)"
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (matches.length > 0) {
                if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                  e.preventDefault();
                  const step = e.key === "ArrowDown" ? 1 : -1;
                  setActive((active + step + matches.length) % matches.length);
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  insert(matches[active].handle);
                  return;
                }
              }
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send();
              }
            }}
            className="placeholder:text-muted-foreground max-h-48 min-h-12 flex-1 resize-none bg-transparent text-sm outline-none"
          />
          <button
            type="button"
            aria-label="Send"
            disabled={disabled || !value.trim()}
            onClick={send}
            className="bg-primary text-primary-foreground flex size-8 shrink-0 items-center justify-center rounded-full disabled:opacity-40"
          >
            <ArrowUpIcon className="size-4" />
          </button>
        </div>
      </div>
      {!hasMention && agents.length > 0 && (
        <p className="text-muted-foreground mt-2 text-xs">
          Mention an agent to start, e.g. @{agents[0].handle}
        </p>
      )}
    </div>
  );
}
