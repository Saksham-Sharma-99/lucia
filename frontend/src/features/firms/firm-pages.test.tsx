import { waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API,
  HttpResponse,
  capture,
  PLATFORM,
  connection,
  fail,
  firm,
  firmDetail,
  http,
  mapping,
  page,
  server,
} from "@/test/api";
import { path, renderApp, screen, search } from "@/test/app";
import { isDisabled } from "@/test/dom";
import { CONNECTORS, connector, tool } from "@/test/fixtures";

const oneFirm = (over: Parameters<typeof firmDetail>[0] = {}) =>
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail(over))),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
  );

describe("firms list and new firm", () => {
  it("the slug follows the name until edited by hand", async () => {
    const app = await renderApp("/firms");
    await app.user.click(
      await screen.findAllByRole("button", { name: /New firm/ }).then((b) => b[0]),
    );
    const dialog = await screen.findByRole("dialog");
    await app.user.type(within(dialog).getByLabelText("Name"), "Smith & Associates");
    expect((within(dialog).getByLabelText("Slug") as HTMLInputElement).value).toBe(
      "smith-and-associates",
    );
    await app.user.type(within(dialog).getByLabelText("Slug"), "-ny");
    await app.user.type(within(dialog).getByLabelText("Name"), " LLP");
    expect((within(dialog).getByLabelText("Slug") as HTMLInputElement).value).toBe(
      "smith-and-associates-ny",
    );
  });

  it("shows the server's field error and opens the new firm on success", async () => {
    let attempt = 0;
    server.use(
      http.post(`${API}/firms`, () =>
        ++attempt === 1
          ? fail(422, "Validation failed", [
              { path: "/slug", code: "taken", message: "Slug is taken" },
            ])
          : HttpResponse.json(firmDetail(), { status: 201 }),
      ),
      http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail())),
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    );
    const app = await renderApp("/firms");
    await app.user.click(
      await screen.findAllByRole("button", { name: /New firm/ }).then((b) => b[0]),
    );
    await app.user.type(await screen.findByLabelText("Name"), "Acme Law");
    await app.user.click(screen.getByRole("button", { name: "Add firm" }));
    await screen.findByText("Slug is taken");
    await app.user.click(screen.getByRole("button", { name: "Add firm" }));
    await waitFor(() => expect(path(app.router)).toBe("/firms/f1"));
    expect(search(app.router).tab).toBe("connections");
  });

  it("pages through firms, and a search goes back to page 1", async () => {
    const asked: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/firms`, ({ request }) => {
        const query = new URL(request.url).searchParams;
        asked.push(query);
        return HttpResponse.json(query.get("q") ? page([]) : page([firm()], { total: 45 }));
      }),
    );
    const app = await renderApp("/firms");
    await app.user.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() => expect(asked.at(-1)?.get("page")).toBe("2"));
    await app.user.type(screen.getByLabelText("Search firms"), "zzz");
    await screen.findByText("No firms match");
    expect(search(app.router)).toMatchObject({ q: "zzz", page: 1 });
    expect(asked.at(-1)?.get("q")).toBe("zzz");
  });

  it("a first run says there are no firms yet", async () => {
    await renderApp("/firms");
    await screen.findByText("No firms yet");
  });

  it("a reopened dialog starts clean", async () => {
    const app = await renderApp("/firms");
    await app.user.click(
      await screen.findAllByRole("button", { name: /New firm/ }).then((b) => b[0]),
    );
    await app.user.type(await screen.findByLabelText("Name"), "Draft");
    await app.user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await app.user.click(screen.getAllByRole("button", { name: /New firm/ })[0]);
    expect(((await screen.findByLabelText("Name")) as HTMLInputElement).value).toBe("");
  });
});

describe("firm detail", () => {
  it("overview save is disabled until something changes", async () => {
    oneFirm();
    const app = await renderApp("/firms/f1");
    const save = await screen.findByRole("button", { name: "Save changes" });
    expect(isDisabled(save)).toBe(true);
    await app.user.type(screen.getByLabelText("Name"), " LLP");
    expect(isDisabled(save)).toBe(false);
  });

  it("overview saves the details, and shows a server error that isn't about a field", async () => {
    oneFirm();
    const sent = capture("patch", `${API}/firms/f1`, () => HttpResponse.json(firmDetail()));
    const app = await renderApp("/firms/f1");
    const name = await screen.findByLabelText("Name");
    await app.user.clear(name);
    await app.user.type(name, "Acme LLP");
    await app.user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(sent.at(-1)).toMatchObject({ name: "Acme LLP" }));
    await screen.findByText("Saved");

    server.use(http.patch(`${API}/firms/f1`, () => fail(409, "Another firm has this name")));
    await app.user.type(name, "!");
    await app.user.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Another firm has this name");
  });

  it("deactivating lists the mappings it will turn off", async () => {
    oneFirm({ mapping_counts: { active: 1, inactive: 0 } });
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping({ status: "active" })]))),
    );
    const app = await renderApp("/firms/f1");
    await app.user.click(await screen.findByRole("button", { name: "Deactivate firm" }));
    await screen.findByText("@records v1");
  });

  it("deactivating doesn't claim nothing is affected when it couldn't check, and can retry", async () => {
    oneFirm();
    let calls = 0;
    server.use(
      http.get(`${API}/mappings`, () =>
        ++calls === 1
          ? fail(500, "Boom")
          : HttpResponse.json(page([mapping({ status: "active" })])),
      ),
    );
    const app = await renderApp("/firms/f1");
    await app.user.click(await screen.findByRole("button", { name: "Deactivate firm" }));
    const confirm = await screen.findByRole("alertdialog");
    await within(confirm).findByText(/Couldn't check which mappings this turns off/);
    expect(within(confirm).queryByText("No agents are active at this firm.")).toBeNull();
    await app.user.click(within(confirm).getByRole("button", { name: "Try again" }));
    await within(confirm).findByText("@records v1");
  });

  it("a failed lookup still lets the admin deactivate", async () => {
    oneFirm();
    server.use(http.get(`${API}/mappings`, () => fail(500, "Boom")));
    const sent = capture("post", `${API}/firms/f1/deactivate`, () =>
      HttpResponse.json(firmDetail({ status: "inactive" })),
    );
    const app = await renderApp("/firms/f1");
    await app.user.click(await screen.findByRole("button", { name: "Deactivate firm" }));
    const confirm = await screen.findByRole("alertdialog");
    await within(confirm).findByText(/Couldn't check/);
    await app.user.click(within(confirm).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(sent).toHaveLength(1));
  });

  it("deactivating calls its endpoint only after confirming", async () => {
    oneFirm();
    const called = capture("post", `${API}/firms/f1/deactivate`, () =>
      HttpResponse.json(firmDetail({ status: "inactive" })),
    );
    const app = await renderApp("/firms/f1");
    await app.user.click(await screen.findByRole("button", { name: "Deactivate firm" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(called).toHaveLength(0);
    await app.user.click(within(confirm).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(called).toHaveLength(1));
    await screen.findByText("Acme Law deactivated");
  });

  it("activating an inactive firm says mappings stay off", async () => {
    oneFirm({ status: "inactive" });
    const looked = capture("get", `${API}/mappings`, () => HttpResponse.json(page([])));
    const called = capture("post", `${API}/firms/f1/activate`, () =>
      HttpResponse.json(firmDetail()),
    );
    const app = await renderApp("/firms/f1");
    await app.user.click(await screen.findByRole("button", { name: "Activate firm" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("Mappings stay off until you turn them on.");
    await app.user.click(within(confirm).getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(called).toHaveLength(1));
    expect(looked).toHaveLength(0); // nothing to turn off, so no lookup
  });

  it("settings refuse business hours that close before they open", async () => {
    oneFirm();
    const saved = capture("patch", `${API}/firms/f1`, () => HttpResponse.json(firmDetail()));
    const app = await renderApp("/firms/f1?tab=settings");
    const closes = await screen.findByLabelText("Monday closes");
    await app.user.clear(closes);
    await app.user.type(closes, "08:00");
    await app.user.click(screen.getByRole("button", { name: "Save settings" }));
    await screen.findByText("Opens before it closes");
    expect(saved).toHaveLength(0);
  });

  it("settings save the whole settings object", async () => {
    oneFirm();
    const sent = capture("patch", `${API}/firms/f1`, () => HttpResponse.json(firmDetail()));
    const app = await renderApp("/firms/f1?tab=settings");
    await app.user.click(await screen.findByRole("switch", { name: "Tuesday open" }));
    await app.user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(sent.at(-1)).toMatchObject({
        settings: {
          business_hours: {
            mon: { start: "09:00", end: "18:00" },
            tue: { start: "09:00", end: "18:00" },
          },
          quiet_hours: { start: "20:00", end: "08:00" },
        },
      }),
    );
    await screen.findByText("Settings saved");
  });

  it("settings map server errors under /settings onto the form", async () => {
    oneFirm();
    server.use(
      http.patch(`${API}/firms/f1`, () =>
        fail(422, "Validation failed", [
          { path: "/settings/quiet_hours/end", code: "x", message: "Quiet hours too long" },
        ]),
      ),
    );
    const app = await renderApp("/firms/f1?tab=settings");
    await app.user.click(await screen.findByRole("switch", { name: "Tuesday open" }));
    await app.user.click(screen.getByRole("button", { name: "Save settings" }));
    await screen.findByText("Quiet hours too long");
  });

  it("has no mappings tab; an old ?tab=mappings link opens the overview", async () => {
    oneFirm();
    await renderApp("/firms/f1?tab=mappings");
    await screen.findByRole("tab", { name: "Overview", selected: true });
    expect(screen.queryByRole("tab", { name: "Mappings" })).toBeNull();
  });
});

describe("connections", () => {
  it("adds gmail as pending, named after the app when no label is given", async () => {
    oneFirm();
    const body = capture("post", `${API}/firms/f1/connections`, () =>
      HttpResponse.json(connection({ status: "pending" }), { status: 201 }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click((await screen.findAllByRole("button", { name: "Add connection" }))[0]);
    const dialog = await screen.findByRole("dialog");
    await app.user.click(within(dialog).getByRole("button", { name: "Add connection" }));
    await waitFor(() => expect(body.at(-1)).toEqual({ connector: "gmail", label: "GMAIL" }));
    await screen.findByText(/Generate its consent link next/);
  });

  it.each([
    ["the platform default number when the id is empty", "", {}],
    ["the firm's own number by its id", " pn_1 ", { phone_number_id: "pn_1" }],
  ])("adds a Vapi connection with %s", async (_, numberId, config) => {
    oneFirm();
    server.use(
      http.get(`${API}/registry/connectors`, () =>
        HttpResponse.json([...CONNECTORS, connector("vapi", [], { setup: "form" })]),
      ),
    );
    const body = capture("post", `${API}/firms/f1/connections`, () =>
      HttpResponse.json(connection({ connector: "vapi", label: "Main line" }), { status: 201 }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click((await screen.findAllByRole("button", { name: "Add connection" }))[0]);
    const dialog = await screen.findByRole("dialog");
    await app.user.click(within(dialog).getByRole("radio", { name: /VAPI/ }));
    await app.user.type(within(dialog).getByLabelText("Label"), "Main line");
    if (numberId)
      await app.user.type(within(dialog).getByLabelText("Vapi phone number id"), numberId);
    await app.user.click(within(dialog).getByRole("button", { name: "Add the number" }));
    await waitFor(() =>
      expect(body.at(-1)).toEqual({ connector: "vapi", label: "Main line", config }),
    );
  });

  it("a server error on add shows in the dialog", async () => {
    oneFirm();
    server.use(
      http.post(`${API}/firms/f1/connections`, () => fail(400, "Mailbox already connected")),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click((await screen.findAllByRole("button", { name: "Add connection" }))[0]);
    const dialog = await screen.findByRole("dialog");
    await app.user.click(within(dialog).getByRole("button", { name: "Add connection" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain(
      "Mailbox already connected",
    );
  });

  it("removing an unused connection asks first", async () => {
    oneFirm();
    server.use(http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])));
    const deleted = capture(
      "delete",
      `${API}/connections/c1`,
      () => new HttpResponse(null, { status: 204 }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Remove records@acme.com" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(deleted).toHaveLength(0);
    await app.user.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleted).toHaveLength(1));
    await screen.findByText("Removed records@acme.com");
  });

  it("a connector whose platform app isn't set up can't be added", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/platform/status`, () =>
        HttpResponse.json({
          slack: true,
          google: false,
          vapi: true,
          public_base_url: "x",
          allowed_models: ["m"],
        }),
      ),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(
      await screen.findAllByRole("button", { name: "Add connection" }).then((b) => b[0]),
    );
    const dialog = await screen.findByRole("dialog");
    within(dialog).getByText(/isn't set up yet/);
    expect(isDisabled(within(dialog).getByRole("button", { name: "Add connection" }))).toBe(true);
  });

  it("lists connections even when the registry fails, with setup turned off", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/registry`, () => fail(500, "Boom")),
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([connection({ status: "pending", secret_hints: {} })]),
      ),
    );
    await renderApp("/firms/f1?tab=connections");
    await screen.findByText("records@acme.com");
    await screen.findByText(/registry didn't load/);
    expect(isDisabled(screen.getByRole("button", { name: "Add connection" }))).toBe(true);
    expect(screen.queryByRole("button", { name: "Generate link" })).toBeNull();
  });

  describe("while a consent link is out", () => {
    afterEach(() => vi.useRealTimers());

    it("polls until the connection is no longer pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      oneFirm();
      let calls = 0;
      server.use(
        http.get(`${API}/firms/f1/connections`, () =>
          HttpResponse.json([
            connection(++calls < 3 ? { status: "pending", secret_hints: {} } : {}),
          ]),
        ),
      );
      await renderApp("/firms/f1?tab=connections");
      await screen.findByRole("button", { name: "Generate link" });
      await vi.advanceTimersByTimeAsync(5000);
      await waitFor(() => expect(calls).toBe(2));
      await vi.advanceTimersByTimeAsync(5000);
      await screen.findByText(/Connected/);
      await vi.advanceTimersByTimeAsync(15000);
      expect(calls).toBe(3);
    });
  });

  it("a connection a mapping uses can't be removed", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([connection({ used_by: ["records"] })]),
      ),
    );
    await renderApp("/firms/f1?tab=connections");
    await screen.findByText(/used by @records/);
    expect(isDisabled(screen.getByRole("button", { name: "Remove records@acme.com" }))).toBe(true);
  });

  it("an outbound test confirms the real target before sending", async () => {
    oneFirm();
    server.use(http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])));
    const sent = capture("post", `${API}/connections/c1/test`, () =>
      HttpResponse.json({ ok: true, detail: "Sent" }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.type(await screen.findByLabelText("Send to"), "me@example.com");
    await app.user.click(screen.getByRole("button", { name: "Send test" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("me@example.com");
    await app.user.click(within(confirm).getByRole("button", { name: "Send test" }));
    await waitFor(() =>
      expect(sent.at(-1)).toEqual({ tool: "gmail.send_email", input: { to: "me@example.com" } }),
    );
  });

  it("Slack's file test asks for a channel ID; its message test also takes a name", async () => {
    oneFirm();
    const channel = { required: ["channel"], properties: { channel: { type: "string" } } };
    server.use(
      http.get(`${API}/registry/connectors`, () =>
        HttpResponse.json([
          connector("slack", [
            tool("slack.send_message", { direction: "outbound", params_schema: channel }),
            tool("slack.post_file", { direction: "outbound", params_schema: channel }),
          ]),
        ]),
      ),
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([connection({ connector: "slack", label: "lucia" })]),
      ),
    );
    await renderApp("/firms/f1?tab=connections");
    expect((await screen.findByLabelText("Slack channel ID")).getAttribute("placeholder")).toBe(
      "C0123456789",
    );
    expect(screen.getByLabelText("Slack channel").getAttribute("placeholder")).toContain(
      "#general",
    );
  });

  it("a pending OAuth connection generates a consent link", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([
          connection({ status: "pending", connected_at: null, secret_hints: {} }),
        ]),
      ),
      http.post(`${API}/connections/c1/consent-link`, () =>
        HttpResponse.json({ url: "https://accounts.google.com/o/oauth2?state=abc" }),
      ),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Generate link" }));
    await screen.findByText("https://accounts.google.com/o/oauth2?state=abc");
  });

  it("a link already shown can be replaced after confirming", async () => {
    oneFirm();
    let n = 0;
    server.use(
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([
          connection({ status: "pending", connected_at: null, secret_hints: {} }),
        ]),
      ),
      http.post(`${API}/connections/c1/consent-link`, () =>
        HttpResponse.json({ url: `https://accounts.google.com/o/oauth2?state=${++n}` }),
      ),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Generate link" }));
    await screen.findByText("https://accounts.google.com/o/oauth2?state=1");
    await app.user.click(screen.getByRole("button", { name: /New link/ }));
    const confirm = await screen.findByRole("alertdialog");
    await app.user.click(within(confirm).getByRole("button", { name: "Make a new link" }));
    await screen.findByText("https://accounts.google.com/o/oauth2?state=2");
    expect(screen.queryByText("https://accounts.google.com/o/oauth2?state=1")).toBeNull();
  });

  it("a test tool whose target the UI doesn't know sends no made-up input", async () => {
    oneFirm();
    const odd = tool("gmail.send_fax_like", {
      direction: "outbound",
      params_schema: {
        type: "object",
        required: ["fax_no"],
        properties: { fax_no: { type: "string" } },
      },
    });
    server.use(
      http.get(`${API}/registry/connectors`, () =>
        HttpResponse.json([connector("gmail", [odd]), ...CONNECTORS.slice(1)]),
      ),
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
    );
    const sent = capture("post", `${API}/connections/c1/test`, () =>
      HttpResponse.json({ ok: false, detail: "fax_no is required" }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Send test" }));
    await app.user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Send test" }),
    );
    await waitFor(() => expect(sent.at(-1)).toEqual({ tool: "gmail.send_fax_like", input: {} }));
    await screen.findByText("gmail.send_fax_like: fax_no is required");
  });

  it("making a new consent link asks first, since the old one stops working", async () => {
    oneFirm();
    let made = 0;
    server.use(
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([
          connection({ status: "pending", has_consent_link: true, secret_hints: {} }),
        ]),
      ),
      http.post(`${API}/connections/c1/consent-link`, () => {
        made++;
        return HttpResponse.json({ url: "https://accounts.google.com/o/oauth2?state=new" });
      }),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Make a new link" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(made).toBe(0);
    await app.user.click(within(confirm).getByRole("button", { name: "Make a new link" }));
    await screen.findByText("https://accounts.google.com/o/oauth2?state=new");
    expect(made).toBe(1);
  });

  it("no consent link can be made while the platform app isn't set up", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/platform/status`, () => HttpResponse.json({ ...PLATFORM, google: false })),
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([connection({ status: "pending", secret_hints: {} })]),
      ),
    );
    await renderApp("/firms/f1?tab=connections");
    await screen.findByText(/platform app isn't set up yet/);
    expect(screen.queryByRole("button", { name: "Generate link" })).toBeNull();
  });

  it("replacing a secret sends only the new value, never showing the old one", async () => {
    oneFirm();
    server.use(http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])));
    const body = capture("patch", `${API}/connections/c1`, () => HttpResponse.json(connection()));
    const app = await renderApp("/firms/f1?tab=connections");
    await screen.findByText("••••1234");
    await app.user.click(screen.getByRole("button", { name: "Replace" }));
    const save = screen.getByRole("button", { name: "Save" });
    expect(isDisabled(save)).toBe(true);
    await app.user.type(screen.getByLabelText("New refresh_token"), "fresh");
    await app.user.click(save);
    await waitFor(() => expect(body.at(-1)).toEqual({ secrets: { refresh_token: "fresh" } }));
    await screen.findByText("Secret replaced");
    expect(screen.queryByLabelText("New refresh_token")).toBeNull();
  });

  it("cancelling a secret replacement sends nothing", async () => {
    oneFirm();
    const sent = capture("patch", `${API}/connections/c1`, () => HttpResponse.json(connection()));
    server.use(http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])));
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Replace" }));
    await app.user.type(screen.getByLabelText("New refresh_token"), "fresh");
    await app.user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("New refresh_token")).toBeNull();
    screen.getByRole("button", { name: "Replace" });
    expect(sent).toHaveLength(0);
  });

  it("a failed sign-in check is shown as a result, not an error", async () => {
    oneFirm();
    server.use(
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
      http.post(`${API}/connections/c1/test`, () =>
        HttpResponse.json({ ok: false, detail: "Token revoked" }),
      ),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await app.user.click(await screen.findByRole("button", { name: "Check sign-in" }));
    await screen.findByText("Sign-in check: Token revoked");
  });

  it("gmail inbound must be enabled before it can be rechecked", async () => {
    oneFirm();
    const enabled = capture("post", `${API}/connections/c1/inbound/enable`, () =>
      HttpResponse.json({
        webhook_url: "https://lucia.test/api/v1/hooks/gmail",
        detail: "Watching the mailbox",
      }),
    );
    const watching = { mailbox: "records@acme.com", watch_expiration: "2026-12-01" };
    server.use(
      http.get(`${API}/firms/f1/connections`, () =>
        HttpResponse.json([connection(enabled.length ? { config: watching } : {})]),
      ),
    );
    const app = await renderApp("/firms/f1?tab=connections");
    await screen.findByText("No events yet");
    await app.user.click(screen.getByRole("button", { name: "Enable inbound" }));
    await screen.findByText("Watching the mailbox");
    await screen.findByRole("button", { name: /Recheck/ });
  });

  it("returning from an approved consent link announces it once and clears the param", async () => {
    oneFirm();
    const app = await renderApp("/firms/f1?tab=connections&connected=c1");
    await screen.findByText("Connected. You can run tests now.");
    await waitFor(() => expect(search(app.router).connected).toBeUndefined());
    expect(search(app.router).tab).toBe("connections");
  });
});
