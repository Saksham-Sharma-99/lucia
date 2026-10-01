import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  API,
  HttpResponse,
  capture,
  agentDetail,
  agentItem,
  connection,
  fail,
  firm,
  http,
  mapping,
  page,
  server,
  version,
  versionSummary,
} from "@/test/api";
import { choose, renderApp, screen, search } from "@/test/app";
import { isChecked, isDisabled } from "@/test/dom";

/** The firm the switcher shows. */
const shownFirm = async () => (await screen.findByRole("combobox", { name: "Firm" })).textContent;

const twoFirms = () =>
  server.use(
    http.get(`${API}/firms`, () =>
      HttpResponse.json(page([firm(), firm({ id: "f2", name: "Johnson Legal" })])),
    ),
  );

describe("firm switcher", () => {
  it("shows the firm in the URL", async () => {
    twoFirms();
    await renderApp("/firm-mappings?firm=f2");
    await waitFor(async () => expect(await shownFirm()).toContain("Johnson Legal"));
  });

  it("falls back to the last firm used, then the first", async () => {
    twoFirms();
    localStorage.setItem("lucia-firm", "f2");
    await renderApp("/firm-mappings");
    await waitFor(async () => expect(await shownFirm()).toContain("Johnson Legal"));
  });

  it("a remembered firm that's gone falls back to the first", async () => {
    twoFirms();
    localStorage.setItem("lucia-firm", "deleted-firm");
    await renderApp("/firm-mappings");
    await waitFor(async () => expect(await shownFirm()).toContain("Acme Law"));
  });

  it("remembers the firm picked", async () => {
    twoFirms();
    await renderApp("/firm-mappings?firm=f1");
    await waitFor(() => expect(localStorage.getItem("lucia-firm")).toBe("f1"));
  });

  it("says when the firm picker is cut off", async () => {
    server.use(http.get(`${API}/firms`, () => HttpResponse.json(page([firm()], { total: 130 }))));
    await renderApp("/firm-mappings");
    await screen.findByText("Showing the first 1 of 130 firms");
  });

  it("explains that mappings need a firm first", async () => {
    await renderApp("/firm-mappings");
    await screen.findByText("No active firms");
  });
});

describe("create mapping", () => {
  const setup = (existing = [mapping()]) => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page(existing))),
      http.get(`${API}/agents`, () => HttpResponse.json(page([agentItem()]))),
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail())),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
      http.get(`${API}/mappings/checklist`, () =>
        HttpResponse.json([
          {
            connector: "gmail",
            required: true,
            connection_id: null,
            ok: false,
            reason: "Pick a gmail connection",
          },
        ]),
      ),
    );
  };

  async function open(app: Awaited<ReturnType<typeof renderApp>>) {
    await app.user.click(await screen.findByRole("button", { name: /Map an agent/ }));
    const dialog = await screen.findByRole("dialog");
    await app.user.click(await within(dialog).findByRole("combobox", { name: "Agent" }));
    await app.user.click(await screen.findByRole("option", { name: /@records/ }));
    return dialog;
  }

  it("can't turn on until every connection is bound", async () => {
    setup();
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await within(dialog).findByText("Pick a gmail connection");
    const turnOn = within(dialog).getByRole("switch", { name: /Turn on now/ });
    expect(isDisabled(turnOn)).toBe(true);
    within(dialog).getByText("Bind every connection first.");
  });

  it("a 409 offers to switch the active mapping's version instead", async () => {
    setup();
    let asked: URLSearchParams | undefined;
    server.use(
      http.get(`${API}/mappings`, ({ request }) => {
        const query = new URL(request.url).searchParams;
        if (query.get("status") !== "active") return HttpResponse.json(page([]));
        asked = query;
        return HttpResponse.json(
          page([mapping({ status: "active", version: 1, agent_prompt_id: "v0" })]),
        );
      }),
      http.post(`${API}/mappings`, () =>
        fail(409, "Another active mapping exists. Use switch-version."),
      ),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await app.user.click(within(dialog).getByRole("button", { name: "Map agent" }));
    await app.user.click(
      await within(dialog).findByRole("button", { name: /Switch v1 to v1 instead/ }),
    );
    await screen.findByRole("heading", { name: /Switch @records from v1/ });
    expect(Object.fromEntries(asked!)).toMatchObject({ firm_id: "f1", agent_id: "a1" });
  });

  it("'switch instead' opens the switch dialog on the version that was picked", async () => {
    setup();
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(
          agentDetail({
            versions: [
              versionSummary({ id: "v3", version: 3 }),
              versionSummary({ id: "v2", version: 2 }),
              versionSummary(),
            ],
          }),
        ),
      ),
      http.get(`${API}/agents/records/versions/:n`, ({ params }) =>
        HttpResponse.json(version({ id: `v${String(params.n)}`, version: Number(params.n) })),
      ),
      http.get(`${API}/agents/records/versions/1/diff/:b`, () => HttpResponse.json([])),
      http.get(`${API}/mappings`, ({ request }) =>
        HttpResponse.json(
          page(
            new URL(request.url).searchParams.get("status") === "active"
              ? [mapping({ status: "active", version: 1, agent_prompt_id: "v1" })]
              : [],
          ),
        ),
      ),
      http.post(`${API}/mappings`, () => fail(409, "Another active mapping exists.")),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await app.user.click(within(dialog).getByRole("combobox", { name: "Version" }));
    await app.user.click(await screen.findByRole("option", { name: /^v2/ }));
    await app.user.click(within(dialog).getByRole("button", { name: "Map agent" }));
    await app.user.click(
      await within(dialog).findByRole("button", { name: "Switch v1 to v2 instead" }),
    );
    const switcher = await screen.findByRole("dialog", { name: /Switch @records from v1/ });
    within(switcher).getByRole("button", { name: "Switch to v2" });
  });

  it("maps without turning on, sending the partial bindings", async () => {
    setup();
    const sent = capture("post", `${API}/mappings`, () =>
      HttpResponse.json(mapping(), { status: 201 }),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await within(dialog).findByText("Pick a gmail connection");
    await app.user.click(within(dialog).getByRole("button", { name: "Map agent" }));
    await waitFor(() =>
      expect(sent.at(-1)).toEqual({
        firm_id: "f1",
        agent_prompt_id: "v1",
        identities: {},
        overrides: {},
        activate: false,
      }),
    );
    await screen.findByText("Mapped @records v1");
  });

  it("maps and turns on in one go once every connection is bound", async () => {
    setup();
    const sent = capture("post", `${API}/mappings`, () =>
      HttpResponse.json(mapping({ status: "active" }), { status: 201 }),
    );
    server.use(
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
      http.get(`${API}/mappings/checklist`, ({ request }) => {
        const bound = new URL(request.url).searchParams.getAll("identities").length > 0;
        return HttpResponse.json([
          {
            connector: "gmail",
            required: true,
            connection_id: null,
            ok: bound,
            reason: bound ? "Connected" : "Pick one",
          },
        ]);
      }),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    const binding = await within(dialog).findByRole("combobox", { name: "Gmail connection" });
    await app.user.click(binding);
    await app.user.click(await screen.findByRole("option", { name: /records@acme.com/ }));
    const turnOn = within(dialog).getByRole("switch", { name: /Turn on now/ });
    await waitFor(() => expect(isDisabled(turnOn)).toBe(false));
    await app.user.click(turnOn);
    await app.user.click(within(dialog).getByRole("button", { name: "Map and turn on" }));
    await waitFor(() =>
      expect(sent.at(-1)).toMatchObject({
        firm_id: "f1",
        agent_prompt_id: "v1",
        identities: { gmail: "c1" },
        activate: true,
      }),
    );
    await screen.findByText("Mapped @records v1 and turned it on");
  });

  it("an agent with no active version says so instead of loading forever", async () => {
    setup();
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(agentDetail({ versions: [versionSummary({ status: "archived" })] })),
      ),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await within(dialog).findByText("This agent has no active version to map.");
  });

  it("a failed connection check says so instead of 'bind every connection'", async () => {
    setup();
    server.use(http.get(`${API}/mappings/checklist`, () => fail(500, "Boom")));
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await within(dialog).findByText(/Couldn't check the connections/);
    expect(within(dialog).queryByText("Bind every connection first.")).toBeNull();
  });

  it("says so when the agents can't be loaded", async () => {
    setup();
    server.use(http.get(`${API}/agents`, () => fail(500, "Boom")));
    const app = await renderApp("/firm-mappings?firm=f1");
    await app.user.click(await screen.findByRole("button", { name: /Map an agent/ }));
    await within(await screen.findByRole("dialog")).findByText("Agents didn't load");
  });

  it("a 409 for the version already running shows the error without a switch offer", async () => {
    setup();
    server.use(
      http.get(`${API}/mappings`, () =>
        HttpResponse.json(page([mapping({ status: "active", agent_prompt_id: "v1" })])),
      ),
      http.post(`${API}/mappings`, () => fail(409, "This version is already mapped here.")),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await app.user.click(within(dialog).getByRole("button", { name: "Map agent" }));
    await within(dialog).findByText("This version is already mapped here.");
    expect(within(dialog).queryByRole("button", { name: /instead/ })).toBeNull();
  });

  it("says when the agent list is cut off", async () => {
    setup();
    server.use(
      http.get(`${API}/agents`, () => HttpResponse.json(page([agentItem()], { total: 150 }))),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await open(app);
    await screen.findByText(/Showing the first 1 of 150 agents/);
  });

  it("picking another version drops overrides made for the last one", async () => {
    setup();
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(
          agentDetail({ versions: [versionSummary({ id: "v2", version: 2 }), versionSummary()] }),
        ),
      ),
      http.get(`${API}/agents/records/versions/2`, () =>
        HttpResponse.json(version({ id: "v2", version: 2 })),
      ),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    const routing = await within(dialog).findByRole("switch", { name: /Route alerts differently/ });
    await app.user.click(routing);
    expect(isChecked(routing)).toBe(true);
    await app.user.click(within(dialog).getByRole("combobox", { name: "Version" }));
    await app.user.click(await screen.findByRole("option", { name: /^v1/ }));
    await waitFor(() =>
      expect(
        isChecked(within(dialog).getByRole("switch", { name: /Route alerts differently/ })),
      ).toBe(false),
    );
  });

  it("a reopened dialog starts clean, without the last error", async () => {
    setup();
    server.use(http.post(`${API}/mappings`, () => fail(400, "Bad request")));
    const app = await renderApp("/firm-mappings?firm=f1");
    const dialog = await open(app);
    await app.user.click(within(dialog).getByRole("button", { name: "Map agent" }));
    await within(dialog).findByText("Bad request");
    await app.user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await app.user.click(screen.getByRole("button", { name: /Map an agent/ }));
    const reopened = await screen.findByRole("dialog");
    expect(within(reopened).queryByText("Bad request")).toBeNull();
  });
});

describe("mapping row actions", () => {
  it("the kill switch asks first, then stops the agent", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () =>
        HttpResponse.json(page([mapping({ status: "active", checklist_ok: true })])),
      ),
    );
    const body = capture("patch", `${API}/mappings/m1`, () =>
      HttpResponse.json(mapping({ kill_switch: true })),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await app.user.click(await screen.findByRole("switch", { name: "Kill switch for @records" }));
    const confirm = await screen.findByRole("alertdialog");
    await app.user.click(within(confirm).getByRole("button", { name: "Stop the agent" }));
    await waitFor(() => expect(body.at(-1)).toEqual({ kill_switch: true }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("releasing the kill switch asks first, then lets the agent act again", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () =>
        HttpResponse.json(page([mapping({ status: "active", kill_switch: true })])),
      ),
    );
    const sent = capture("patch", `${API}/mappings/m1`, () =>
      HttpResponse.json(mapping({ status: "active" })),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await app.user.click(await screen.findByRole("switch", { name: "Kill switch for @records" }));
    const confirm = await screen.findByRole("alertdialog", { name: /Release the kill switch/ });
    await app.user.click(within(confirm).getByRole("button", { name: "Release" }));
    await waitFor(() => expect(sent.at(-1)).toEqual({ kill_switch: false }));
    await screen.findByText("@records is on");
  });

  it("turning an inactive mapping on sends status active", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping({ status: "inactive" })]))),
    );
    const sent = capture("patch", `${API}/mappings/m1`, () =>
      HttpResponse.json(mapping({ status: "active" })),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", "Turn on");
    const confirm = await screen.findByRole("alertdialog", { name: "Turn on @records?" });
    await app.user.click(within(confirm).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(sent.at(-1)).toEqual({ status: "active" }));
  });

  it("a failed update says why and leaves the row as it was", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping({ status: "inactive" })]))),
      http.patch(`${API}/mappings/m1`, () => fail(422, "Bind every connection first")),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", "Turn on");
    await app.user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Turn on" }),
    );
    await screen.findByText("Bind every connection first");
    within(screen.getByText("@records").closest("tr")!).getByText("inactive");
  });

  it("a failed list offers a retry; an empty one offers to map an agent", async () => {
    twoFirms();
    let calls = 0;
    server.use(
      http.get(`${API}/mappings`, () =>
        ++calls === 1 ? fail(500, "Database is down") : HttpResponse.json(page([])),
      ),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await screen.findByText("Mappings didn't load");
    await app.user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("No agents mapped to this firm");
    await app.user.click(screen.getAllByRole("button", { name: /Map an agent/ }).at(-1)!);
    await screen.findByRole("dialog", { name: "Map an agent to this firm" });
  });

  it("turning a mapping off asks first, then sends the new status", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping({ status: "active" })]))),
    );
    const body = capture("patch", `${API}/mappings/m1`, () =>
      HttpResponse.json(mapping({ status: "inactive" })),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", "Turn off");
    const confirm = await screen.findByRole("alertdialog");
    expect(body).toHaveLength(0);
    await app.user.click(within(confirm).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(body.at(-1)).toEqual({ status: "inactive" }));
    await screen.findByText("@records is off");
  });

  it("editing saves the bindings and overrides together", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([connection()])),
      http.get(`${API}/mappings/checklist`, () => HttpResponse.json([])),
    );
    const body = capture("patch", `${API}/mappings/m1`, () => HttpResponse.json(mapping()));
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", /Edit connections/);
    const dialog = await screen.findByRole("dialog");
    await app.user.click(await within(dialog).findByRole("combobox", { name: "Gmail connection" }));
    await app.user.click(await screen.findByRole("option", { name: /records@acme.com/ }));
    await app.user.click(within(dialog).getByRole("switch", { name: /Route alerts differently/ }));
    await app.user.click(within(dialog).getByRole("button", { name: "Save mapping" }));
    await waitFor(() =>
      expect(body.at(-1)).toMatchObject({
        identities: { gmail: "c1" },
        overrides: { alert_routing: { P0: ["slack_dm"] } },
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the page in the URL, and a firm switch starts at page 1", async () => {
    twoFirms();
    const pages: (string | null)[] = [];
    server.use(
      http.get(`${API}/mappings`, ({ request }) => {
        pages.push(new URL(request.url).searchParams.get("page"));
        return HttpResponse.json(page([mapping()], { total: 45 }));
      }),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await app.user.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() => expect(search(app.router)).toMatchObject({ firm: "f1", page: 2 }));
    expect(pages.at(-1)).toBe("2");
    await app.user.click(screen.getByRole("combobox", { name: "Firm" }));
    await app.user.click(await screen.findByRole("option", { name: "Johnson Legal" }));
    await waitFor(() => expect(search(app.router)).toMatchObject({ firm: "f2", page: 1 }));
  });

  it("editing shows a server error inside the dialog, and a failed version load", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
      http.get(`${API}/agents/records/versions/1`, () => fail(500, "Boom")),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", /Edit connections/);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("v1 didn't load");

    server.use(
      http.patch(`${API}/mappings/m1`, () =>
        fail(422, "Overrides too loose", [
          { path: "/overrides/cadence", code: "x", message: "Can only go up" },
        ]),
      ),
    );
    await app.user.click(within(dialog).getByRole("button", { name: "Save mapping" }));
    await within(dialog).findByText("Overrides too loose");
    within(dialog).getByText("Can only go up");
  });

  describe("switch version", () => {
    const twoVersions = () =>
      server.use(
        http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
        http.get(`${API}/agents/records`, () =>
          HttpResponse.json(
            agentDetail({ versions: [versionSummary({ id: "v2", version: 2 }), versionSummary()] }),
          ),
        ),
        http.get(`${API}/agents/records/versions/1/diff/2`, () =>
          HttpResponse.json([
            { path: "/system_prompt", op: "change", before: "Old", after: "New" },
          ]),
        ),
      );
    const openSwitch = async () => {
      const app = await renderApp("/firm-mappings?firm=f1");
      await choose(app, "Actions for @records", "Switch version");
      return { app, dialog: await screen.findByRole("dialog") };
    };

    it("shows what changes, then switches", async () => {
      twoFirms();
      twoVersions();
      const sent = capture("post", `${API}/mappings/m1/switch-version`, () =>
        HttpResponse.json(mapping({ version: 2, status: "active" })),
      );
      const { app, dialog } = await openSwitch();
      await within(dialog).findByText("New");
      await app.user.click(within(dialog).getByRole("button", { name: "Switch to v2" }));
      await waitFor(() => expect(sent.at(-1)).toEqual({ agent_prompt_id: "v2" }));
      await screen.findByText("Now running v2");
    });

    it("warns when the new version still needs connections", async () => {
      twoFirms();
      twoVersions();
      capture("post", `${API}/mappings/m1/switch-version`, () =>
        HttpResponse.json(mapping({ version: 2, status: "inactive", checklist_missing: 1 })),
      );
      const { app, dialog } = await openSwitch();
      await app.user.click(await within(dialog).findByRole("button", { name: "Switch to v2" }));
      await screen.findByText("Switched to v2, but it's off: 1 connection(s) to bind");
    });

    it("a failed switch says so and keeps the dialog open", async () => {
      twoFirms();
      twoVersions();
      server.use(
        http.post(`${API}/mappings/m1/switch-version`, () => fail(409, "Version archived")),
      );
      const { app, dialog } = await openSwitch();
      await app.user.click(await within(dialog).findByRole("button", { name: "Switch to v2" }));
      await screen.findByText("Switch failed: Version archived");
      screen.getByRole("dialog");
    });

    it("a failed agent load isn't mistaken for 'nothing to switch to'", async () => {
      twoFirms();
      server.use(
        http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
        http.get(`${API}/agents/records`, () => fail(500, "Boom")),
      );
      const { dialog } = await openSwitch();
      await within(dialog).findByText("@records didn't load");
      expect(within(dialog).queryByText(/no other active version/)).toBeNull();
    });
  });

  it("switch version says when there's nothing to switch to", async () => {
    twoFirms();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping()]))),
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail())),
    );
    const app = await renderApp("/firm-mappings?firm=f1");
    await choose(app, "Actions for @records", "Switch version");
    await screen.findByText("There's no other active version to switch to.");
  });
});
