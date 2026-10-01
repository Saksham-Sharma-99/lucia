import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { API, HttpResponse, connection, http, server, version } from "@/test/api";
import { VERSION_CONFIG, rule } from "@/test/fixtures";

import { MappingEditor } from "./mapping-editor";
import type { MappingDraft } from "./model";

const CAP = rule("per_subject_contact_cap", {
  type: "object",
  required: ["n"],
  properties: { n: { type: "integer", minimum: 1 } },
});

/** The editor is controlled; hold its value like the dialogs do and report every change. */
function Harness({ onChange }: { onChange: (d: MappingDraft) => void }) {
  const [draft, setDraft] = useState<MappingDraft>({ identities: {}, overrides: {} });
  return (
    <MappingEditor
      firmId="f1"
      version={version({
        config: {
          ...VERSION_CONFIG,
          policy_pack: [{ rule: "per_subject_contact_cap", params: { n: 3 } }],
        },
      })}
      rules={[CAP]}
      value={draft}
      onChange={(d) => {
        setDraft(d);
        onChange(d);
      }}
    />
  );
}

const setup = async () => {
  server.use(
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
    http.get(`${API}/mappings/checklist`, () => HttpResponse.json([])),
  );
  const onChange = vi.fn();
  // The editor links to the firm's connections tab, so it needs a router around it.
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <Harness onChange={onChange} /> }),
    history: createMemoryHistory(),
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("switch", { name: "Override follow-up cadence" });
  const last = () => onChange.mock.lastCall?.[0] as MappingDraft;
  return { last, user: userEvent.setup() };
};

describe("MappingEditor overrides", () => {
  it("cadence starts at the version's wait and can't go below it", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("switch", { name: "Override follow-up cadence" }));
    expect(last().overrides.cadence).toEqual({ min_wait_hours: 48 });
    const hours = screen.getByLabelText("Minimum wait in hours");
    await user.clear(hours);
    await user.type(hours, "12");
    await user.tab();
    expect(last().overrides.cadence).toEqual({ min_wait_hours: 48 });
    await user.click(screen.getByRole("switch", { name: "Override follow-up cadence" }));
    expect(last().overrides.cadence).toBeNull();
  });

  it("alert routing starts from defaults and edits per urgency", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("switch", { name: /Route alerts differently/ }));
    expect(last().overrides.alert_routing).toEqual({
      P0: ["slack_dm"],
      P1: ["slack_thread"],
      P2: ["digest"],
    });
    const p2 = screen.getByText("P2").parentElement!;
    await user.click(within(p2).getByRole("checkbox", { name: "Email" }));
    expect(last().overrides.alert_routing?.P2).toEqual(["email", "digest"]); // option order
  });

  it("tightening a rule starts from the version's params; turning it off clears it", async () => {
    const { last, user } = await setup();
    const toggle = screen.getByRole("switch", { name: /Tighten/ });
    await user.click(toggle);
    expect(last().overrides.policy_params).toEqual({ per_subject_contact_cap: { n: 3 } });
    await user.click(toggle);
    expect(last().overrides.policy_params).toBeNull();
  });

  it("binds a connection per connector", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: /records@acme.com/ }));
    expect(last().identities).toEqual({ gmail: "c1" });
  });
});
