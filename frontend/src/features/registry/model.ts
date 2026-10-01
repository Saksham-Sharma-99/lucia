import type { ConnectorOut, PlatformStatus } from "@/api/generated/types.gen";
import { isConfigured } from "@/features/firms/model";

/** Whether firms can connect it today: the app exists and its platform credentials are set. */
export type ConnectorState = "ready" | "needs setup" | "coming soon";

export function connectorState(c: ConnectorOut, platform: PlatformStatus): ConnectorState {
  if (!c.available) return "coming soon";
  return isConfigured(platform, c.name) ? "ready" : "needs setup";
}

export const HOW_IT_CONNECTS: Record<string, string> = {
  oauth_link: "Each firm's admin approves a consent link",
  form: "Set up per firm from details entered in Lucia",
  none: "Nothing to connect per firm",
};

/** Case-insensitive "any field contains q". */
export const matches = (q: string, ...fields: (string | null | undefined)[]) =>
  !q || fields.some((f) => f?.toLowerCase().includes(q.toLowerCase()));
