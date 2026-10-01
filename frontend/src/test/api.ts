/** A mock Lucia API for page tests: typed data builders plus default handlers. */
import { http, HttpResponse, type JsonBodyType } from "msw";
import { setupServer } from "msw/node";

import type {
  AgentDetail,
  AgentListItem,
  ConnectionOut,
  FirmDetail,
  FirmOut,
  MappingOut,
  PlatformStatus,
  Problem,
  RegistryEntryOut,
  UserOut,
  VersionDetail,
  VersionSummary,
} from "@/api/generated/types.gen";

import { CONNECTORS, VERSION_CONFIG, rule } from "./fixtures";

export const API = "http://test/api/v1";
const NOW = "2026-10-01T12:00:00Z";

export const page = <T>(
  items: T[],
  over: { page?: number; limit?: number; total?: number } = {},
) => ({
  items,
  total: over.total ?? items.length,
  page: over.page ?? 1,
  limit: over.limit ?? 20,
});

export const problem = (
  status: number,
  detail: string,
  errors: Problem["errors"] = [],
): Problem => ({
  type: "about:blank",
  title: detail,
  status,
  detail,
  errors,
});

export const fail = (status: number, detail: string, errors: Problem["errors"] = []) =>
  HttpResponse.json(problem(status, detail, errors) as JsonBodyType, { status });

export const user = (): UserOut => ({
  id: "u1",
  username: "saksham",
  display_name: "Saksham",
  role: "builder",
});

export const agentItem = (over: Partial<AgentListItem> = {}): AgentListItem => ({
  id: "a1",
  handle: "records",
  name: "Medical Records Follow-up",
  description: "Chases records",
  is_template: false,
  status: "active",
  latest_version: 1,
  latest_active_version: 1,
  active_mapping_count: 0,
  updated_at: NOW,
  ...over,
});

export const versionSummary = (over: Partial<VersionSummary> = {}): VersionSummary => ({
  id: "v1",
  version: 1,
  status: "active",
  changelog: "Initial version",
  parent_version: null,
  created_by: "u1",
  created_by_name: "Saksham",
  created_at: NOW,
  config_hash: "5be3d12ea7bb",
  mapping_count: 0,
  ...over,
});

export const version = (over: Partial<VersionDetail> = {}): VersionDetail => ({
  ...versionSummary(),
  config: VERSION_CONFIG,
  ...over,
});

export const agentDetail = (over: Partial<AgentDetail> = {}): AgentDetail => ({
  id: "a1",
  handle: "records",
  name: "Medical Records Follow-up",
  description: "Chases records",
  use_cases: ["get records"],
  is_template: false,
  source_agent_id: null,
  is_callable: true,
  auto_delegate: false,
  version_policy: "pin",
  status: "active",
  active_mapping_count: 0,
  created_at: NOW,
  updated_at: NOW,
  versions: [versionSummary()],
  ...over,
});

export const firm = (over: Partial<FirmOut> = {}): FirmOut => ({
  id: "f1",
  name: "Acme Law",
  slug: "acme-law",
  timezone: "America/New_York",
  status: "active",
  color: "#d4a24c",
  settings: {
    business_hours: { mon: { start: "09:00", end: "18:00" } },
    quiet_hours: { start: "20:00", end: "08:00" },
    alert_routing: {},
    policy_floor: [],
  },
  created_at: NOW,
  updated_at: NOW,
  ...over,
});

export const firmDetail = (over: Partial<FirmDetail> = {}): FirmDetail => ({
  ...firm(),
  connection_counts: {},
  mapping_counts: { active: 0, inactive: 0 },
  ...over,
});

export const mapping = (over: Partial<MappingOut> = {}): MappingOut => ({
  id: "m1",
  firm_id: "f1",
  firm_name: "Acme Law",
  agent_id: "a1",
  agent_prompt_id: "v1",
  identities: {},
  overrides: {},
  ab_weight: 100,
  status: "inactive",
  kill_switch: false,
  supersedes_mapping_id: null,
  mapped_by: "u1",
  mapped_at: NOW,
  agent_handle: "records",
  agent_name: "Medical Records Follow-up",
  version: 1,
  checklist_ok: false,
  checklist_missing: 1,
  ...over,
});

export const connection = (over: Partial<ConnectionOut> = {}): ConnectionOut => ({
  id: "c1",
  firm_id: "f1",
  connector: "gmail",
  label: "records@acme.com",
  status: "connected",
  config: { mailbox: "records@acme.com" },
  secret_hints: { refresh_token: "••••1234" },
  has_consent_link: false,
  connected_at: NOW,
  health: "ok",
  test_results: {},
  last_tested_at: null,
  last_inbound_at: null,
  last_inbound_type: null,
  webhook_url: "https://lucia.test/api/v1/hooks/gmail",
  used_by: [],
  created_at: NOW,
  updated_at: NOW,
  ...over,
});

export const PLATFORM: PlatformStatus = {
  slack: true,
  google: true,
  vapi: true,
  twilio: true,
  public_base_url: "https://lucia.test",
  allowed_models: ["m-big", "m-small"],
};

const ENTRIES: RegistryEntryOut[] = [
  ...CONNECTORS.flatMap((c) => c.tools),
  rule("recipient_must_be_contact", { type: "object", properties: {} }),
  {
    ...rule("email", {}),
    kind: "channel",
    display_name: "Email",
    channel_tool: "gmail.send_email",
  },
];

/** Serve one endpoint and record each request's JSON body (null when empty), to assert what was sent. */
export function capture(
  method: "get" | "post" | "patch" | "delete",
  url: string,
  reply: () => Response = () => HttpResponse.json({}),
) {
  const sent: unknown[] = [];
  server.use(
    http[method](url, async ({ request }) => {
      const text = await request.text();
      sent.push(text ? JSON.parse(text) : null);
      return reply();
    }),
  );
  return sent;
}

/** Handlers every page needs: signed in, registry loaded, empty lists. */
export const defaults = [
  http.get(`${API}/auth/me`, () => HttpResponse.json(user())),
  http.get(`${API}/registry/connectors`, () => HttpResponse.json(CONNECTORS)),
  http.get(`${API}/registry`, () => HttpResponse.json(ENTRIES)),
  http.get(`${API}/platform/status`, () => HttpResponse.json(PLATFORM)),
  http.get(`${API}/agents`, () => HttpResponse.json(page([]))),
  http.get(`${API}/firms`, () => HttpResponse.json(page([]))),
  http.get(`${API}/mappings`, () => HttpResponse.json(page([]))),
  http.post(`${API}/agents/validate`, () => HttpResponse.json({ errors: [] })),
];

export const server = setupServer(...defaults);
export { http, HttpResponse };
