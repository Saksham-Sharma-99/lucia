import { waitFor } from "@testing-library/react";
import { within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  API,
  HttpResponse,
  agentDetail,
  agentItem,
  fail,
  http,
  page,
  server,
  version,
  versionSummary,
} from "@/test/api";
import { openMenu, path, renderApp, screen, search } from "@/test/app";
import { isDisabled } from "@/test/dom";
import { VERSION_CONFIG } from "@/test/fixtures";

const step = (name: RegExp) =>
  within(screen.getByRole("navigation", { name: "Steps" })).getByRole("button", { name });

const templates = () =>
  server.use(
    http.get(`${API}/agents`, () => HttpResponse.json(page([agentItem({ is_template: true })]))),
    http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail({ is_template: true }))),
    http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
  );

describe("new agent wizard", () => {
  it("blocks Next until the step is valid", async () => {
    const app = await renderApp("/agents/new");
    await app.user.click(await screen.findByRole("button", { name: /Blank agent/ }));
    await app.user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(/3–32 lowercase letters/);
    screen.getByText("Name the agent");
    expect(step(/Basic info/).getAttribute("aria-current")).toBe("step");
  });

  it("can't jump ahead to steps not reached yet, including Review", async () => {
    const app = await renderApp("/agents/new");
    await app.user.click(await screen.findByRole("button", { name: /Blank agent/ }));
    expect(isDisabled(step(/Review/))).toBe(true);
    expect(isDisabled(step(/Start/))).toBe(false);
  });

  it("prefills every step from a template, leaving the handle for the builder", async () => {
    templates();
    await renderApp("/agents/new?template=records");
    expect(((await screen.findByLabelText("Name")) as HTMLInputElement).value).toBe(
      "Medical Records Follow-up",
    );
    expect((screen.getByLabelText("Handle") as HTMLInputElement).value).toBe("");
    screen.getByText("get records");
  });

  it("says when a template can't be used instead of opening a blank form", async () => {
    server.use(http.get(`${API}/agents/ghost`, () => fail(404, "Agent @ghost not found")));
    await renderApp("/agents/new?template=ghost");
    await screen.findByText("Template @ghost can't be used");
    screen.getByText("Agent @ghost not found");
  });

  it("creates the agent and opens it; a server error jumps to the step that owns it", async () => {
    templates();
    let attempt = 0;
    server.use(
      http.post(`${API}/agents`, async ({ request }) => {
        const body = (await request.json()) as { handle: string; source_agent_id: string };
        expect(body.source_agent_id).toBe("a1");
        if (++attempt === 1)
          return fail(422, "Validation failed", [
            { path: "/config/system_prompt", code: "x", message: "Too vague" },
          ]);
        return HttpResponse.json(agentDetail({ handle: body.handle }), { status: 201 });
      }),
      http.get(`${API}/agents/chaser`, () => HttpResponse.json(agentDetail({ handle: "chaser" }))),
    );
    const app = await renderApp("/agents/new?template=records");
    await app.user.type(await screen.findByLabelText("Handle"), "chaser");
    for (let i = 0; i < 5; i++) await app.user.click(screen.getByRole("button", { name: "Next" }));
    await app.user.click(await screen.findByRole("button", { name: "Create agent" }));
    await screen.findByText("Too vague");
    expect(step(/Prompt and models/).getAttribute("aria-current")).toBe("step");
    for (let i = 0; i < 3; i++) await app.user.click(screen.getByRole("button", { name: "Next" }));
    await app.user.click(await screen.findByRole("button", { name: "Create agent" }));
    await waitFor(() => expect(path(app.router)).toBe("/agents/chaser"));
  });

  it("a taken handle sends the builder back to Basic info", async () => {
    templates();
    server.use(http.post(`${API}/agents`, () => fail(409, "Handle @records is taken")));
    const app = await renderApp("/agents/new?template=records");
    await app.user.type(await screen.findByLabelText("Handle"), "records");
    for (let i = 0; i < 5; i++) await app.user.click(screen.getByRole("button", { name: "Next" }));
    await app.user.click(await screen.findByRole("button", { name: "Create agent" }));
    await screen.findByText("Handle @records is taken");
    expect(step(/Basic info/).getAttribute("aria-current")).toBe("step");
  });

  it("shows the server's verdict on Review", async () => {
    templates();
    server.use(
      http.post(`${API}/agents/validate`, () =>
        fail(422, "Validation failed", [
          {
            path: "/config/models/loop",
            code: "model_not_allowed",
            message: "Model m-big is not allowed",
          },
        ]),
      ),
    );
    const app = await renderApp("/agents/new?template=records");
    await app.user.type(await screen.findByLabelText("Handle"), "chaser");
    for (let i = 0; i < 5; i++) await app.user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(/Model m-big is not allowed/);
    await app.user.click(screen.getByRole("button", { name: /Prompt and models:/ }));
    expect(step(/Prompt and models/).getAttribute("aria-current")).toBe("step");
  });
});

describe("agent detail", () => {
  const detail = (status: "active" | "archived" = "active") =>
    server.use(
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail({ status }))),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version({ status }))),
    );

  it("shows the overview and version facts, without a firms section", async () => {
    detail();
    await renderApp("/agents/records");
    await screen.findByRole("heading", { name: "@records" });
    await screen.findByText(/by Saksham/);
    expect(screen.queryByText("Firms using it")).toBeNull();
    screen.getByRole("img", { name: "How @records works" });
  });

  it("keeps the Versions tab usable when the selected version fails to load", async () => {
    server.use(
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail())),
      http.get(`${API}/agents/records/versions/1`, () => fail(500, "Boom")),
    );
    await renderApp("/agents/records?tab=versions");
    await screen.findByRole("columnheader", { name: "Saved by" });
    within(screen.getByRole("table")).getByText("Saksham");
  });

  it("disables amend for an archived agent", async () => {
    detail("archived");
    await renderApp("/agents/records");
    const amend = await screen.findByRole("button", { name: /Amend v1/ });
    expect(isDisabled(amend)).toBe(true);
  });

  it("each model role explains what it is used for", async () => {
    detail();
    const app = await renderApp("/agents/records?tab=prompt");
    await app.user.hover(
      await screen.findByRole("button", { name: "What the guardrail model does" }),
    );
    await screen.findByText(/Checks every outgoing email, call or message/);
    screen.getByRole("button", { name: "What the loop model does" });
    screen.getByRole("button", { name: "What the judge model does" });
  });

  it("evals is a placeholder for now", async () => {
    detail();
    await renderApp("/agents/records?tab=evals");
    await screen.findByText("Evals are coming soon");
  });

  it("keeps Versions and Evals usable when the registry fails", async () => {
    detail();
    server.use(http.get(`${API}/registry`, () => fail(500, "Boom")));
    const app = await renderApp("/agents/records?tab=prompt");
    await screen.findByText("v1 didn't load");
    await app.user.click(screen.getByRole("tab", { name: "Versions" }));
    await screen.findByRole("columnheader", { name: "Saved by" });
  });

  it("opens the newest active version when none is picked", async () => {
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(
          agentDetail({
            versions: [
              versionSummary({ id: "v1", version: 1 }),
              versionSummary({ id: "v3", version: 3, status: "archived" }),
              versionSummary({ id: "v2", version: 2 }),
            ],
          }),
        ),
      ),
      http.get(`${API}/agents/records/versions/2`, () =>
        HttpResponse.json(version({ id: "v2", version: 2 })),
      ),
    );
    await renderApp("/agents/records");
    await screen.findByRole("button", { name: /Amend v2/ });
  });
});

describe("versions tab", () => {
  const two = (mappingCount = 0) =>
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(
          agentDetail({
            versions: [
              versionSummary({
                id: "v2",
                version: 2,
                changelog: "Shorter",
                mapping_count: mappingCount,
              }),
              versionSummary(),
            ],
          }),
        ),
      ),
    );

  it("compares two versions", async () => {
    two();
    server.use(
      http.get(`${API}/agents/records/versions/1/diff/2`, () =>
        HttpResponse.json([{ path: "/system_prompt", op: "change", before: "Old", after: "New" }]),
      ),
    );
    const app = await renderApp("/agents/records?tab=versions");
    await app.user.click(await screen.findByRole("button", { name: "Show changes" }));
    await screen.findByText("v1 → v2");
    await screen.findByText("New");
  });

  it("archives a version, but not one a mapping uses", async () => {
    two(1);
    let archived = "";
    server.use(
      http.post(`${API}/agents/records/versions/:n/archive`, ({ params }) => {
        archived = String(params.n);
        return HttpResponse.json(version({ status: "archived" }));
      }),
    );
    const app = await renderApp("/agents/records?tab=versions");
    await openMenu(app, "Actions for v2");
    expect(isDisabled(await screen.findByRole("menuitem", { name: "In use by a mapping" }))).toBe(
      true,
    );
    await app.user.keyboard("{Escape}");
    await app.user.click(screen.getByRole("button", { name: "Actions for v1" }));
    await app.user.click(await screen.findByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(archived).toBe("1"));
    await screen.findByText("Archived v1");
  });
});

describe("amend", () => {
  const base = () =>
    server.use(
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail())),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
    );

  it("can't save until something changed, and marks changed sections", async () => {
    base();
    const app = await renderApp("/agents/records/amend?from=1");
    const save = await screen.findByRole("button", { name: "Save as v2" });
    expect(isDisabled(save)).toBe(true);
    await app.user.click(screen.getByRole("tab", { name: "Prompt and models" }));
    await app.user.type(screen.getByLabelText("System prompt"), " Be brief.");
    await screen.findByLabelText("changed");
    expect(isDisabled(save)).toBe(false);
  });

  it("needs a version note, then saves v2 from v1", async () => {
    base();
    let body:
      { from_version: number; config: typeof VERSION_CONFIG; changelog: string } | undefined;
    server.use(
      http.post(`${API}/agents/records/versions`, async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json(version({ id: "v2", version: 2, parent_version: 1 }), {
          status: 201,
        });
      }),
    );
    const app = await renderApp("/agents/records/amend?from=1");
    await app.user.click(await screen.findByRole("tab", { name: "Prompt and models" }));
    await app.user.type(screen.getByLabelText("System prompt"), " Be brief.");
    await app.user.click(screen.getByRole("button", { name: "Save as v2" }));
    await screen.findByText("Say what changed");
    await app.user.type(screen.getByLabelText("What changed"), "Shorter");
    await app.user.click(screen.getByRole("button", { name: "Save as v2" }));
    await waitFor(() => expect(search(app.router)).toMatchObject({ v: 2 }));
    expect(body).toMatchObject({
      from_version: 1,
      changelog: "Shorter",
      config: { system_prompt: "Chase records. Be brief." },
    });
  });

  it("asks before leaving with unsaved changes", async () => {
    base();
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const app = await renderApp("/agents/records/amend?from=1");
    await app.user.click(await screen.findByRole("tab", { name: "Prompt and models" }));
    await app.user.type(screen.getByLabelText("System prompt"), " Be brief.");
    await app.user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(path(app.router)).toBe("/agents/records/amend");
    await app.user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(path(app.router)).toBe("/agents/records"));
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("an agent field that breaks today's rules doesn't block a new version", async () => {
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(agentDetail({ description: "x".repeat(2500) })),
      ),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
      http.post(`${API}/agents/records/versions`, () =>
        HttpResponse.json(version({ id: "v2", version: 2 }), { status: 201 }),
      ),
    );
    const app = await renderApp("/agents/records/amend?from=1");
    await app.user.click(await screen.findByRole("tab", { name: "Prompt and models" }));
    await app.user.type(screen.getByLabelText("System prompt"), " Be brief.");
    await app.user.type(screen.getByLabelText("What changed"), "Shorter");
    await app.user.click(screen.getByRole("button", { name: "Save as v2" }));
    await waitFor(() => expect(search(app.router)).toMatchObject({ v: 2 }));
  });

  it("refuses to amend an archived agent", async () => {
    server.use(
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(agentDetail({ status: "archived" })),
      ),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
    );
    await renderApp("/agents/records/amend?from=1");
    await screen.findByText("@records is archived");
  });
});
