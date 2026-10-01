import { waitFor, within } from "@testing-library/react";
import { delay } from "msw";
import { describe, expect, it } from "vitest";

import {
  API,
  HttpResponse,
  agentDetail,
  agentItem,
  capture,
  fail,
  http,
  mapping,
  page,
  server,
} from "@/test/api";
import { choose, openMenu, path, renderApp, screen, search } from "@/test/app";
import { isDisabled, stat } from "@/test/dom";

/** Serve the agents list, recording each request's query string. */
function agents(items = [agentItem()], over: Parameters<typeof page>[1] = {}) {
  const seen: URLSearchParams[] = [];
  server.use(
    http.get(`${API}/agents`, ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json(page(items, over));
    }),
  );
  return seen;
}

describe("agents list", () => {
  it("shows each agent as a card with its version, status and firms", async () => {
    agents([agentItem({ latest_version: 3, active_mapping_count: 2 })]);
    const app = await renderApp("/agents");
    const card = (await screen.findByRole("link", { name: "@records" })).closest("li")!;
    expect(card.textContent).toContain("v3 · 2 firms");
    within(card).getByText("active");
    await app.user.click(within(card).getByRole("link", { name: "@records" }));
    await waitFor(() => expect(path(app.router)).toBe("/agents/records"));
  });

  it("stat cards and filters count agents by status, templates and live mappings", async () => {
    const totals = { active: 7, archived: 2, template: 3 };
    server.use(
      http.get(`${API}/agents`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        const total =
          q.get("is_template") === "true"
            ? totals.template
            : q.get("status") === "archived"
              ? totals.archived
              : totals.active;
        return HttpResponse.json(page([agentItem()], { total }));
      }),
      http.get(`${API}/mappings`, () => HttpResponse.json(page([], { total: 5 }))),
    );
    await renderApp("/agents");
    await waitFor(() => expect(stat("Active agents")).toBe("7"));
    expect(stat("Live mappings")).toBe("5");
    expect(stat("Templates")).toBe("3");
    const filters = within(screen.getByRole("group", { name: "Show" }));
    filters.getByRole("button", { name: "All 9" });
    filters.getByRole("button", { name: "Archived 2" });
  });

  it("quick filters switch status or templates and reset to page 1", async () => {
    const seen = agents([agentItem()], { page: 2, total: 40 });
    const app = await renderApp("/agents?page=2");
    const filters = within(await screen.findByRole("group", { name: "Show" }));
    await app.user.click(filters.getByRole("button", { name: /^Templates/ }));
    await waitFor(() => expect(search(app.router)).toMatchObject({ templates: true, page: 1 }));
    expect(seen.at(-1)?.get("is_template")).toBe("true");
    await app.user.click(filters.getByRole("button", { name: /^Archived/ }));
    await waitFor(() => expect(search(app.router).status).toBe("archived"));
    expect(search(app.router).templates).toBeUndefined();
    expect(filters.getByRole("button", { name: /^Archived/ }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    await app.user.click(filters.getByRole("button", { name: /^All/ }));
    await waitFor(() => expect(search(app.router).status).toBeUndefined());
  });

  it("asks for 12 agents a page, a full card grid", async () => {
    const seen = agents();
    await renderApp("/agents");
    await screen.findByRole("link", { name: "@records" });
    expect(seen.some((q) => q.get("limit") === "12")).toBe(true);
  });

  it("debounces search into the URL and follows the URL when it changes elsewhere", async () => {
    const seen = agents();
    const app = await renderApp("/agents");
    const box = await screen.findByLabelText("Search agents");
    await app.user.type(box, "lien");
    await waitFor(() => expect(search(app.router).q).toBe("lien"));
    await waitFor(() => expect(seen.at(-1)?.get("q")).toBe("lien"));
    await app.router.navigate({ to: "/agents", search: { page: 1 } }); // e.g. the sidebar link
    await waitFor(() => expect((box as HTMLInputElement).value).toBe(""));
  });

  it("pages through results", async () => {
    agents([agentItem()], { total: 45 });
    const app = await renderApp("/agents");
    await screen.findByText("1–20 of 45");
    await app.user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(search(app.router).page).toBe(2));
  });

  it("a page past the end offers the first page instead of claiming there are no agents", async () => {
    agents([], { page: 3, total: 5 });
    const app = await renderApp("/agents?page=3");
    await app.user.click(await screen.findByRole("button", { name: "Go to the first page" }));
    await waitFor(() => expect(search(app.router).page).toBe(1));
  });

  it("explains an empty first run and an empty search differently", async () => {
    agents([]);
    const app = await renderApp("/agents");
    await screen.findByText("No agents yet");
    await app.router.navigate({ to: "/agents", search: { q: "zzz", page: 1 } });
    await screen.findByText("No agents match");
  });

  it("shows a load error with a working retry", async () => {
    let attempts = 0;
    server.use(
      http.get(`${API}/agents`, () =>
        ++attempts === 1 ? fail(500, "Database is down") : HttpResponse.json(page([agentItem()])),
      ),
    );
    const app = await renderApp("/agents");
    await screen.findByText("Database is down");
    await app.user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("@records");
  });
});

describe("agent actions", () => {
  it("disables amend and duplicate for an archived agent", async () => {
    agents([agentItem({ status: "archived" })]);
    const app = await renderApp("/agents");
    await openMenu(app, "Actions for @records");
    expect(isDisabled(await screen.findByRole("menuitem", { name: "Amend v1" }))).toBe(true);
    expect(isDisabled(screen.getByRole("menuitem", { name: "Duplicate" }))).toBe(true);
    screen.getByRole("menuitem", { name: "Unarchive" });
  });

  it("duplicate creates the copy and opens it", async () => {
    agents();
    const sent = capture("post", `${API}/agents/records/duplicate`, () =>
      HttpResponse.json(agentDetail({ handle: "records-copy" }), { status: 201 }),
    );
    server.use(
      http.get(`${API}/agents/records-copy`, () =>
        HttpResponse.json(agentDetail({ handle: "records-copy" })),
      ),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Duplicate");
    const dialog = await screen.findByRole("dialog");
    await app.user.click(within(dialog).getByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(path(app.router)).toBe("/agents/records-copy"));
    expect(sent.at(-1)).toEqual({
      handle: "records-copy",
      name: "Medical Records Follow-up (copy)",
    });
    await screen.findByText("Created @records-copy");
  });

  it("a taken duplicate handle shows on the field", async () => {
    agents();
    server.use(
      http.post(`${API}/agents/records/duplicate`, () =>
        fail(409, "Handle taken", [
          { path: "/handle", code: "taken", message: "That handle is taken" },
        ]),
      ),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Duplicate");
    const dialog = await screen.findByRole("dialog");
    await app.user.click(within(dialog).getByRole("button", { name: "Duplicate" }));
    await within(dialog).findByText("That handle is taken");
  });

  it("unarchive asks first, then reactivates", async () => {
    agents([agentItem({ status: "archived" })]);
    const sent = capture("post", `${API}/agents/records/unarchive`, () =>
      HttpResponse.json(agentDetail()),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Unarchive");
    const confirm = await screen.findByRole("alertdialog");
    expect(sent).toHaveLength(0);
    await app.user.click(within(confirm).getByRole("button", { name: "Unarchive" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    await screen.findByText("Unarchived @records");
  });

  it("archive lists the firms whose mappings turn off, with a remainder", async () => {
    agents();
    server.use(
      http.get(`${API}/mappings`, () =>
        HttpResponse.json(
          page([mapping({ firm_name: "Smith & Associates", status: "active" })], { total: 3 }),
        ),
      ),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Archive");
    await screen.findByText("Smith & Associates (v1)");
    screen.getByText("and 2 more");
  });

  it("archive doesn't claim no firm is affected when it couldn't check", async () => {
    agents();
    server.use(http.get(`${API}/mappings`, () => fail(500, "Boom")));
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Archive");
    const confirm = await screen.findByRole("alertdialog");
    await within(confirm).findByText(/Couldn't check which mappings this turns off/);
    expect(within(confirm).queryByText(/No firm is using it/)).toBeNull();
  });

  it("archive turns the agent off after confirming, and Cancel sends nothing", async () => {
    agents();
    server.use(
      http.get(`${API}/mappings`, () => HttpResponse.json(page([mapping({ status: "active" })]))),
    );
    const sent = capture("post", `${API}/agents/records/archive`, () =>
      HttpResponse.json({
        agent: agentDetail({ status: "archived" }),
        deactivated_mapping_ids: ["m1"],
      }),
    );
    const app = await renderApp("/agents");
    const openArchive = async () => {
      await choose(app, "Actions for @records", "Archive");
      return screen.findByRole("alertdialog");
    };
    await app.user.click(within(await openArchive()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(sent).toHaveLength(0);

    const confirm = await openArchive();
    await within(confirm).findByText(/\(v1\)/); // lists what it turns off
    await app.user.click(within(confirm).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    await screen.findByText("Archived @records; 1 mapping turned off");
  });

  it("a failed lookup still lets the builder archive", async () => {
    agents();
    server.use(http.get(`${API}/mappings`, () => fail(500, "Boom")));
    const sent = capture("post", `${API}/agents/records/archive`, () =>
      HttpResponse.json({
        agent: agentDetail({ status: "archived" }),
        deactivated_mapping_ids: [],
      }),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Archive");
    const confirm = await screen.findByRole("alertdialog");
    await within(confirm).findByText(/Couldn't check/);
    await app.user.click(within(confirm).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(sent).toHaveLength(1));
  });

  it("View opens the agent; an archived agent's menu offers Unarchive, not Archive", async () => {
    agents([agentItem({ status: "archived" })]);
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(agentDetail({ status: "archived" })),
      ),
    );
    const app = await renderApp("/agents");
    await openMenu(app, "Actions for @records");
    const view = await screen.findByRole("menuitem", { name: "View" });
    screen.getByRole("menuitem", { name: "Unarchive" });
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    await app.user.click(view);
    await waitFor(() => expect(path(app.router)).toBe("/agents/records"));
  });

  it("archive can't be confirmed until it knows what it turns off", async () => {
    agents();
    server.use(http.get(`${API}/mappings`, () => delay("infinite")));
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Archive");
    const confirm = await screen.findByRole("alertdialog");
    within(confirm).getByText(/Checking which mappings/);
    expect(isDisabled(within(confirm).getByRole("button", { name: "Archive" }))).toBe(true);
  });

  it("duplicate needs a name for the copy", async () => {
    agents();
    const sent = capture("post", `${API}/agents/records/duplicate`);
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Duplicate");
    const dialog = await screen.findByRole("dialog");
    await app.user.clear(within(dialog).getByLabelText("Name"));
    await app.user.click(within(dialog).getByRole("button", { name: "Duplicate" }));
    await within(dialog).findByText("Name the copy");
    expect(sent).toHaveLength(0);
  });

  it("duplicate shows the server's conflict and keeps the dialog open", async () => {
    agents();
    server.use(
      http.post(`${API}/agents/records/duplicate`, () =>
        fail(409, "Handle @records-copy is taken"),
      ),
    );
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Duplicate");
    expect((screen.getByLabelText("Handle") as HTMLInputElement).value).toBe("records-copy");
    await app.user.click(screen.getByRole("button", { name: "Duplicate" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Handle @records-copy is taken");
  });

  it("duplicate validates the handle before calling the API", async () => {
    agents();
    const app = await renderApp("/agents");
    await choose(app, "Actions for @records", "Duplicate");
    const handle = screen.getByLabelText("Handle");
    await app.user.clear(handle);
    await app.user.type(handle, "Bad Handle");
    await app.user.click(screen.getByRole("button", { name: "Duplicate" }));
    await screen.findByText(/3–32 lowercase letters/);
  });
});
