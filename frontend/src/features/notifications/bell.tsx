import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { BellIcon } from "lucide-react";
import { useState } from "react";

import {
  listNotificationsOptions,
  markAllNotificationsReadMutation,
  markNotificationReadMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { NotificationOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import { relativeTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";
import { cn } from "@/lib/utils";

const DOT: Record<string, string> = {
  P0: "bg-destructive",
  P1: "bg-amber-500",
  P2: "bg-muted-foreground/50",
};

/** In-app attention alerts: a count in the sidebar and a list that opens the run. */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const notes = useQuery({ ...listNotificationsOptions(), refetchInterval: 15_000 });
  const items = notes.data ?? [];
  const unread = items.filter((n) => !n.read_at).length;
  const markRead = useApiMutation(markNotificationReadMutation(), { stale: STALE.notification });
  const markAll = useApiMutation(markAllNotificationsReadMutation(), {
    stale: STALE.notification,
  });

  const openOne = (n: NotificationOut) => {
    if (!n.read_at) markRead.mutate({ path: { notification_id: n.id } });
    setOpen(false);
    if (n.run_id)
      void navigate({
        to: "/runs/$runId",
        params: { runId: n.run_id },
        search: { tab: "attention" },
      });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <SidebarMenuButton
            tooltip="Notifications"
            aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          />
        }
      >
        <BellIcon />
        <span>Notifications</span>
        {unread > 0 && (
          <span className="bg-brass text-background ml-auto rounded-full px-1.5 text-xs font-semibold tabular-nums">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent side="right" align="end" className="w-96 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <p className="font-medium">Notifications</p>
          {unread > 0 && (
            <Button
              size="sm"
              variant="ghost"
              disabled={markAll.isPending}
              onClick={() => markAll.mutate({})}
            >
              Mark all read
            </Button>
          )}
        </div>
        {items.length === 0 ? (
          <p className="text-muted-foreground px-3 py-8 text-center text-sm">
            You're all caught up
          </p>
        ) : (
          <ScrollArea className="max-h-96">
            <ul className="divide-y">
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => openOne(n)}
                    className={cn(
                      "hover:bg-muted flex w-full gap-3 px-3 py-2.5 text-left text-sm",
                      n.read_at && "text-muted-foreground",
                    )}
                  >
                    <span
                      className={cn(
                        "mt-1.5 size-2 shrink-0 rounded-full",
                        DOT[n.urgency] ?? DOT.P2,
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block", !n.read_at && "font-medium")}>{n.summary}</span>
                      <span className="text-muted-foreground text-xs">
                        {relativeTime(n.created_at)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </ScrollArea>
        )}
      </PopoverContent>
    </Popover>
  );
}
