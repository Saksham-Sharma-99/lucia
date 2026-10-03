import type { ConversationOut } from "@/api/generated/types.gen";

const DAY = 86_400_000;

/** Chats by how recent their last message is, newest group first; empty groups dropped. */
export function groupByAge(conversations: ConversationOut[], now = Date.now()) {
  const today = new Date(now).setHours(0, 0, 0, 0);
  const groups = [
    { label: "Today", since: today },
    { label: "Previous 7 days", since: today - 7 * DAY },
    { label: "Previous 30 days", since: today - 30 * DAY },
    { label: "Older", since: -Infinity },
  ];
  const bucket = (c: ConversationOut) =>
    groups.findIndex((g) => Date.parse(c.last_message_at) >= g.since);
  return groups
    .map((g, i) => ({ label: g.label, items: conversations.filter((c) => bucket(c) === i) }))
    .filter((g) => g.items.length > 0);
}
