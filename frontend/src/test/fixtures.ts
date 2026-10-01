import type { ConnectorOut, RegistryEntryOut, VersionConfig } from "@/api/generated/types.gen";

const entry = (over: Partial<RegistryEntryOut>): RegistryEntryOut => ({
  kind: "tool",
  name: "",
  connector: null,
  display_name: "",
  description: "",
  params_schema: {},
  risk_tier: null,
  direction: null,
  is_async: false,
  available: true,
  version: 1,
  channel_tool: null,
  ...over,
});

export const tool = (name: string, over: Partial<RegistryEntryOut> = {}) =>
  entry({ name, connector: name.split(".")[0], display_name: name.split(".")[1], ...over });

export const connector = (
  name: string,
  tools: RegistryEntryOut[],
  over: Partial<ConnectorOut> = {},
): ConnectorOut => ({
  ...entry({
    kind: "connector",
    name,
    display_name: name.toUpperCase(),
    description: `${name} app`,
  }),
  setup: "oauth_link",
  tools,
  ...over,
});

export const rule = (name: string, params_schema: Record<string, unknown>) =>
  entry({ kind: "policy_rule", name, display_name: name, params_schema });

export const CONNECTORS: ConnectorOut[] = [
  connector("gmail", [
    tool("gmail.send_email", {
      direction: "outbound",
      risk_tier: "external_comm",
      params_schema: { type: "object", required: ["to"], properties: { to: { type: "string" } } },
    }),
    tool("gmail.read_thread", { direction: "inbound", risk_tier: "read" }),
  ]),
  connector("fax", [tool("fax.send_fax")], { available: false }),
];

export const VERSION_CONFIG: VersionConfig = {
  system_prompt: "Chase records.",
  models: { loop: "m-big", guardrail: "m-small", judge: "m-big" },
  capabilities: [{ connector: "gmail", tools: ["gmail.send_email"] }],
  follow_up: {
    mode: "fixed_ladder",
    ladder: [
      { channel: "email", wait_hours: 48, attempts: 2 },
      { action: "escalate", wait_hours: 0, urgency: "P1" },
    ],
  },
  policy_pack: [{ rule: "recipient_must_be_contact", params: {} }],
  alert_policy: { default_channels: { P0: ["slack_dm"] } },
};
