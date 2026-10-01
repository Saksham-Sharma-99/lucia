import type { MappingOut, Overrides, VersionDetail } from "@/api/generated/types.gen";

export const MAPPING_TABS = [
  "overview",
  "policies",
  "capabilities",
  "prompt",
  "schedules",
  "history",
] as const;
export type MappingTab = (typeof MAPPING_TABS)[number];

export type MappingDraft = { identities: Record<string, string>; overrides: Overrides };

/** The shortest wait in the version's follow-up; cadence overrides can only raise it. */
export function baseMinWait(version: VersionDetail): number {
  const fu = version.config.follow_up;
  if (fu?.mode === "dynamic" && fu.dynamic) return fu.dynamic.min_hours;
  const waits = (fu?.ladder ?? []).filter((r) => r.channel).map((r) => r.wait_hours);
  return waits.length ? Math.min(...waits) : 0;
}

/** Bindings for the connectors this version uses (a version switch can drop some). */
export function bindingsFor(
  version: VersionDetail,
  identities: Record<string, string>,
): Record<string, string> {
  const used = new Set(version.config.capabilities.map((c) => c.connector));
  return Object.fromEntries(
    Object.entries(identities).filter(([connector]) => used.has(connector)),
  );
}

const LAST_FIRM = "lucia-firm";

export function readLastFirm(): string | undefined {
  try {
    return localStorage.getItem(LAST_FIRM) ?? undefined;
  } catch {
    return undefined;
  }
}

export function rememberFirm(id: string) {
  try {
    localStorage.setItem(LAST_FIRM, id);
  } catch {
    /* private mode: just not remembered */
  }
}

export type Confirm = "kill" | "toggle";

export function stateOf(m: MappingOut) {
  if (m.kill_switch) return "stopped by the kill switch";
  return m.status === "active" ? "on" : "off";
}

/** The kill switch and on/off both flip one field, so they share one confirm dialog. */
export function confirmBody(kind: Confirm, m: MappingOut) {
  return kind === "kill"
    ? { kill_switch: !m.kill_switch }
    : { status: m.status === "active" ? ("inactive" as const) : ("active" as const) };
}

export function confirmCopy(kind: Confirm, m: MappingOut, firmName: string) {
  const agent = `@${m.agent_handle}`;
  if (kind === "kill")
    return m.kill_switch
      ? {
          title: `Release the kill switch for ${agent}?`,
          description: "The agent may act again at this firm.",
          confirmLabel: "Release",
        }
      : {
          title: `Stop ${agent} at ${firmName}?`,
          description:
            "The agent stops acting at this firm right away, until you release the switch.",
          confirmLabel: "Stop the agent",
          destructive: true,
        };
  return m.status === "active"
    ? {
        title: `Turn off ${agent}?`,
        description: "It stops picking up new work at this firm.",
        confirmLabel: "Turn off",
      }
    : {
        title: `Turn on ${agent}?`,
        description: "Every connection must be bound and connected.",
        confirmLabel: "Turn on",
      };
}
