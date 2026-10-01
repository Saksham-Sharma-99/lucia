import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MappingResolved } from "@/api/generated/types.gen";
import {
  API,
  HttpResponse,
  capture,
  connection,
  fail,
  firm,
  http,
  mapping,
  page,
  server,
  version,
} from "@/test/api";
import { path, renderApp, screen } from "@/test/app";
import { isChecked } from "@/test/dom";

const resolved = (over: Partial<MappingResolved> = {}): MappingResolved => ({
  policies: [
    {
      rule: "recipient_must_be_contact",
      display_name: "Recipient must be a contact",
      description: "Only send to contacts on the matter.",
      required: true,
      sources: [{ source: "version", params: {}, applies: true }],
    },
    {
      rule: "per_subject_contact_cap",
      display_name: "Contact cap per matter",
      description: "Maximum contacts per day.",
      required: false,
      sources: [
        { source: "version", params: { n: 3 }, applies: false },
        { source: "firm", params: { n: 2 }, applies: false },
        { source: "mapping", params: { n: 1 }, applies: true },
      ],
    },
  ],
  cadence: { version_min_wait_hours: 48, override_min_wait_hours: 72, min_wait_hours: 72 },
  alert_routing: [
    {
      urgency: "P0",
      channels: ["email"],
      source: "mapping",
      version: ["slack_dm"],
      firm: null,
      mapping: ["email"],
    },
    {
      urgency: "P1",
      channels: ["slack_thread"],
      source: "firm",
      version: null,
      firm: ["slack_thread"],
      mapping: null,
    },
    { urgency: "P2", channels: [], source: null, version: null, firm: null, mapping: null },
  ],
  timezone: "America/New_York",
  business_hours: { mon: { start: "09:00", end: "18:00" }, sat: null },
  quiet_hours: { start: "20:00", end: "08:00" },
  history: [],
  ...over,
});

const serve = (over: Partial<MappingResolved> = {}) =>
  server.use(
    http.get(`${API}/mappings/m1`, () =>
      HttpResponse.json(
        mapping({ status: "active", kill_switch: true, identities: { gmail: "c1" } }),
      ),
    ),
    http.get(`${API}/mappings/m1/resolved`, () => HttpResponse.json(resolved(over))),
    http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
    http.get(`${API}/mappings/checklist`, () =>
      HttpResponse.json([
        { connector: "gmail", required: true, connection_id: "c1", ok: true, reason: "Connected" },
      ]),
    ),
  );

describe("mapping detail", () => {
  it("overview: the agent, its state at this firm, and each bound connection", async () => {
    serve();
    await renderApp("/firm-mappings/m1");
    await screen.findByRole("heading", { name: "@records v1" });
    screen.getByText("stopped");
    screen.getByRole("link", { name: "Acme Law" });
    await screen.findByRole("link", { name: "@records v1" });
    expect(isChecked(screen.getByRole("switch", { name: "Kill switch" }))).toBe(true);
    expect(screen.queryByText("Status")).toBeNull();
    const gmail = (await screen.findByText("records@acme.com")).closest("li")!;
    within(gmail).getByText("Connected");
  });

  it("overview: the diagram shows the rules, routing and cadence that apply at this firm", async () => {
    serve();
    await renderApp("/firm-mappings/m1");
    const diagram = await screen.findByRole("img", { name: "How @records works" });
    const text = diagram.textContent;
    expect(text).toContain("Contact cap per matter: Limit 1"); // the mapping's stricter value
    expect(text).toContain("Recipient must be a contact");
    expect(text).toContain("P0 to Email");
    expect(text).toContain("P2 to nowhere");
    expect(text).toMatch(/at least 3d between/);
  });

  it("overview: with no rules the policy box shows its stub, and no cadence line", async () => {
    serve({
      policies: [],
      cadence: { version_min_wait_hours: 48, override_min_wait_hours: null, min_wait_hours: 48 },
    });
    await renderApp("/firm-mappings/m1");
    const diagram = await screen.findByRole("img", { name: "How @records works" });
    expect(diagram.textContent).toContain("No policy rules yet");
    expect(diagram.textContent).not.toMatch(/between contacts/);
  });

  it("the kill switch asks first, saves, and closes the dialog", async () => {
    serve();
    const body = capture("patch", `${API}/mappings/m1`, () =>
      HttpResponse.json(mapping({ status: "active" })),
    );
    const app = await renderApp("/firm-mappings/m1");
    await app.user.click(await screen.findByRole("switch", { name: "Kill switch" }));
    const confirm = await screen.findByRole("alertdialog", { name: /Release the kill switch/ });
    await app.user.click(within(confirm).getByRole("button", { name: "Release" }));
    await waitFor(() => expect(body.at(-1)).toEqual({ kill_switch: false }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await screen.findByText("@records is on");
  });

  it("cancelling the kill switch sends nothing", async () => {
    serve();
    const body = capture("patch", `${API}/mappings/m1`, () => HttpResponse.json(mapping()));
    const app = await renderApp("/firm-mappings/m1");
    await app.user.click(await screen.findByRole("switch", { name: "Kill switch" }));
    const confirm = await screen.findByRole("alertdialog");
    await app.user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(body).toEqual([]);
  });

  it("policies: what applies and where each setting comes from", async () => {
    serve();
    const app = await renderApp("/firm-mappings/m1?tab=policies");
    const cap = (await screen.findByText("Contact cap per matter")).closest("li")!;
    const line = (source: string) => within(cap).getByText(source).closest("li")!;
    expect(line("This mapping").textContent).toContain("Limit 1");
    expect(line("This mapping").className).not.toContain("line-through");
    expect(line("Firm policy floor").className).toContain("line-through"); // replaced
    screen.getByText(/required by the platform/);
    screen.getByText(
      /At least 3d between contacts, set by this mapping \(the agent version.s minimum is 2d\)/,
    );
    const p0 = screen.getByText("P0").closest("li")!;
    expect(p0.textContent).toContain("Email · from this mapping");
    expect(p0.textContent).toContain("Agent version: Slack DM");
    expect(screen.getByText("P2").closest("li")!.textContent).toContain("Nowhere");
    screen.getByText("In America/New_York.");
    expect(screen.getByText("Saturday").nextElementSibling?.textContent).toBe("Closed");
    expect(screen.getByText("Monday").nextElementSibling?.textContent).toBe("09:00–18:00");
    await app.user.click(screen.getByRole("tab", { name: "Capabilities" }));
    await screen.findByText("send_email");
  });

  it("an agent with no rules or follow-up says so instead of leaving gaps", async () => {
    serve({
      policies: [],
      cadence: { version_min_wait_hours: 0, override_min_wait_hours: null, min_wait_hours: 0 },
    });
    await renderApp("/firm-mappings/m1?tab=policies");
    await screen.findByText("No policy rules apply to this agent here.");
    screen.getByText("No minimum wait: the agent version doesn't follow up.");
  });

  it("cadence without an override follows the agent version", async () => {
    serve({
      cadence: { version_min_wait_hours: 48, override_min_wait_hours: null, min_wait_hours: 48 },
    });
    await renderApp("/firm-mappings/m1?tab=policies");
    await screen.findByText(/as the agent version sets it/);
  });

  it("history lists the mappings this one replaced", async () => {
    serve({
      history: [{ id: "m0", version: 1, status: "inactive", mapped_at: "2026-09-01T00:00:00Z" }],
    });
    const app = await renderApp("/firm-mappings/m1?tab=history");
    await app.user.click(await screen.findByRole("link", { name: "v1" }));
    await waitFor(() => expect(path(app.router)).toBe("/firm-mappings/m0"));
  });

  it("a first mapping says it has no history", async () => {
    serve();
    await renderApp("/firm-mappings/m1?tab=history");
    await screen.findByText("This is the first mapping of @records here.");
  });

  it("a missing mapping says it didn't load", async () => {
    server.use(http.get(`${API}/mappings/m1`, () => fail(404, "Mapping not found")));
    await renderApp("/firm-mappings/m1");
    await screen.findByText("This mapping didn't load");
  });

  it("the mappings list links each agent to its mapping", async () => {
    server.use(
      http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
    );
    serve();
    const app = await renderApp("/firm-mappings?firm=f1");
    await app.user.click(await screen.findByRole("link", { name: "@records" }));
    await waitFor(() => expect(path(app.router)).toBe("/firm-mappings/m1"));
  });
});
