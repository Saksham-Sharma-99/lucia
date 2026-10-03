import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, http, page, server } from "@/test/api";
import { path, renderApp, screen, search } from "@/test/app";
import { playgroundApi, TODAY } from "@/test/playground";
import { conversation } from "@/test/runtime";

const list = () => screen.findByRole("navigation", { name: "Chats" });

describe("playground chat list", () => {
  it("fills the screen and groups chats by age", async () => {
    playgroundApi({
      chats: [
        conversation({ id: "c1", title: "Jane check-in", last_message_at: TODAY }),
        conversation({
          id: "c2",
          title: "Records for Doe",
          last_message_at: "2025-01-01T00:00:00Z",
        }),
      ],
    });
    await renderApp("/playground");
    const nav = within(await list());
    await nav.findByText("Jane check-in");
    nav.getByText("Today");
    nav.getByText("Older");
    expect(document.querySelector("main")?.className).not.toContain("max-w");
  });

  it("searches chats", async () => {
    const asked = playgroundApi();
    const app = await renderApp("/playground");
    await within(await list()).findByText("Jane check-in");
    await app.user.type(screen.getByLabelText("Search chats"), "jane");
    await waitFor(() => expect(asked.at(-1)?.get("q")).toBe("jane"));
  });

  it("opens a chat, and New chat goes back to an empty one", async () => {
    playgroundApi();
    server.use(
      http.get(`${API}/conversations/c1`, () => HttpResponse.json(conversation())),
      http.get(`${API}/conversations/c1/messages`, () => HttpResponse.json(page([]))),
      http.get(`${API}/conversations/c1/runs`, () => HttpResponse.json([])),
      http.get(`${API}/conversations/c1/events`, () => new HttpResponse(null, { status: 204 })),
    );
    const app = await renderApp("/playground");
    await app.user.click(await within(await list()).findByText("Jane check-in"));
    await waitFor(() => expect(path(app.router)).toBe("/playground/c1"));
    await app.user.click(screen.getByRole("button", { name: "New chat" }));
    await waitFor(() => expect(path(app.router)).toBe("/playground"));
  });

  it("switching firm starts over in that firm", async () => {
    playgroundApi();
    const app = await renderApp("/playground");
    await within(await list()).findByText("Jane check-in");
    await app.user.click(screen.getByRole("combobox", { name: "Firm" }));
    await app.user.click(await screen.findByRole("option", { name: "Smith & Associates" }));
    await waitFor(() => expect(search(app.router).firm).toBe("f2"));
  });

  it("renames a chat", async () => {
    playgroundApi();
    const sent: unknown[] = [];
    server.use(
      http.patch(`${API}/conversations/c1`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(conversation({ title: "Jane — October" }));
      }),
    );
    const app = await renderApp("/playground");
    const nav = within(await list());
    await nav.findByText("Jane check-in");
    await app.user.click(nav.getByRole("button", { name: "Actions for Jane check-in" }));
    await app.user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const input = nav.getByRole("textbox", { name: "Chat title" });
    await app.user.clear(input);
    await app.user.type(input, "Jane — October{Enter}");
    await waitFor(() => expect(sent).toEqual([{ title: "Jane — October" }]));
  });
});
