import { z } from "zod";

import type { ConnectionOut, PlatformStatus } from "@/api/generated/types.gen";

export const FIRM_TABS = ["overview", "settings", "connections"] as const;
export type FirmTab = (typeof FIRM_TABS)[number];

export const DAYS = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
] as const;

export const FIRM_COLORS = [
  "#d4a24c",
  "#4cb38a",
  "#7a9be0",
  "#c77dba",
  "#e0636b",
  "#5fb7c9",
  "#a3a86b",
];

/** "Smith & Associates" -> "smith-and-associates" (max 40, what the API accepts). */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/, "");
}

/** The editable firm details; the slug is set once, on create. */
export const firmDetailsSchema = z.object({
  name: z.string().trim().min(1, "Name the firm").max(120),
  timezone: z.string().min(1, "Pick a timezone"),
  color: z.string(),
});
export const newFirmSchema = firmDetailsSchema.extend({
  slug: z.string().regex(/^[a-z0-9-]{2,40}$/, "2–40 lowercase letters, digits or -"),
});
export type FirmDetails = z.infer<typeof firmDetailsSchema>;

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const windowSchema = z.object({
  start: z.string().regex(HHMM, "Use HH:MM"),
  end: z.string().regex(HHMM, "Use HH:MM"),
});
const channels = z.array(z.enum(["slack_dm", "slack_thread", "email", "digest"]));

/** Firm settings as the form edits them. Business hours must open before they close;
 *  quiet hours may wrap past midnight (20:00–08:00). */
export const settingsSchema = z.object({
  business_hours: z.record(
    z.string(),
    windowSchema
      .refine((w) => w.start < w.end, { message: "Opens before it closes", path: ["end"] })
      .nullable(),
  ),
  quiet_hours: windowSchema
    .refine((w) => w.start !== w.end, { message: "Start and end differ", path: ["end"] })
    .nullable(),
  alert_routing: z.object({ P0: channels, P1: channels, P2: channels }),
  policy_floor: z.array(z.object({ rule: z.string(), params: z.record(z.string(), z.unknown()) })),
});
export type SettingsForm = z.infer<typeof settingsSchema>;

type Setup = {
  platformKey: keyof PlatformStatus;
  /** Who approves the consent link (OAuth connectors only, so `SETUP.gmail.admin` is typed). */
  admin?: string;
  labelPlaceholder: string;
  labelHint: string;
  /** What a builder does to produce an inbound event for the inbound tests. */
  inboundAsk: (c: ConnectionOut) => string;
};

/** Everything connector-specific the connections screens need, in one place. */
export const SETUP = {
  gmail: {
    platformKey: "google",
    admin: "Google Workspace admin",
    labelPlaceholder: "records@smithlaw.com",
    labelHint: "Replaced by the mailbox once connected.",
    inboundAsk: (c) =>
      `Send an email to ${String(c.config.mailbox ?? "the mailbox")}, then recheck.`,
  },
  slack: {
    platformKey: "slack",
    admin: "Slack workspace admin",
    labelPlaceholder: "Smith & Associates Slack",
    labelHint: "Replaced by the workspace name once connected.",
    inboundAsk: () => "Mention the bot in a channel it's in, then recheck.",
  },
  vapi: {
    platformKey: "vapi",
    labelPlaceholder: "Main line",
    labelHint: "Defaults to the phone number.",
    inboundAsk: (c) => `Call ${String(c.config.phone_number ?? "the number")}, then recheck.`,
  },
} satisfies Record<"gmail" | "slack" | "vapi", Setup>;
export type SetupConnector = keyof typeof SETUP;

export const isSetupConnector = (name: string): name is SetupConnector => name in SETUP;

/** Whether the platform-wide app registration for a connector is set (backend .env). */
export function isConfigured(platform: PlatformStatus | undefined, connector: string): boolean {
  if (!platform || !isSetupConnector(connector)) return true;
  return platform[SETUP[connector].platformKey] === true;
}

/** The input an outbound tool test needs, keyed by the tool's required param. */
export const TEST_TARGET: Record<string, { label: string; placeholder: string }> = {
  channel: { label: "Slack channel", placeholder: "C0123456 or #general" },
  to: { label: "Send to", placeholder: "name@example.com or +14155550123" },
};
