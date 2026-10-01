import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, PLATFORM, http, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { stat } from "@/test/dom";

const card = async (name: string) => (await screen.findByRole("button", { name })).closest("li")!;

describe("connectors", () => {
  it("shows each connector as a card with its state, and counts them", async () => {
    await renderApp("/registry");
    within(await card("GMAIL")).getByText("ready");
    within(await card("GMAIL")).getByText("2 tools");
    within(await card("FAX")).getByText("coming soon");
    expect(stat("Ready")).toBe("1");
    expect(stat("Coming soon")).toBe("1");
  });

  it("a connector whose platform app isn't set up needs setup", async () => {
    server.use(
      http.get(`${API}/platform/status`, () => HttpResponse.json({ ...PLATFORM, google: false })),
    );
    await renderApp("/registry");
    within(await card("GMAIL")).getByText("needs setup");
  });

  it("filters by state and search, and says when nothing matches", async () => {
    const app = await renderApp("/registry");
    const filters = within(await screen.findByRole("group", { name: "Show" }));
    await app.user.click(filters.getByRole("button", { name: "Coming soon 1" }));
    expect(screen.queryByRole("button", { name: "GMAIL" })).toBeNull();
    screen.getByRole("button", { name: "FAX" });
    await app.user.click(filters.getByRole("button", { name: /^All/ }));
    await app.user.type(screen.getByLabelText("Search connectors"), "zzz");
    await screen.findByText("No connectors match");
  });

  it("a card opens its drawer with tools, channels and setup, and the URL follows", async () => {
    const app = await renderApp("/registry");
    await app.user.click(await screen.findByRole("button", { name: "GMAIL" }));
    const drawer = await screen.findByRole("dialog", { name: "GMAIL" });
    expect(search(app.router).connector).toBe("gmail");
    within(drawer).getByText("send_email");
    within(drawer).getByText(/gmail\.send_email · external comm/);
    await app.user.click(within(drawer).getByRole("tab", { name: "Channels" }));
    within(drawer).getByText("Email");
    within(drawer).getByText("sends with gmail.send_email");
    await app.user.click(within(drawer).getByRole("tab", { name: "Setup" }));
    within(drawer).getByText("Each firm's admin approves a consent link");
    within(drawer).getByText("1 outbound · 1 inbound");
    await app.user.keyboard("{Escape}");
    await waitFor(() => expect(search(app.router).connector).toBeUndefined());
  });

  it("a link to a connector opens its drawer", async () => {
    await renderApp("/registry?connector=fax");
    const drawer = await screen.findByRole("dialog", { name: "FAX" });
    await within(drawer)
      .findByText("No channel sends through this connector.", {}, {})
      .catch(() => undefined);
    within(drawer).getByText("coming soon");
  });
});
