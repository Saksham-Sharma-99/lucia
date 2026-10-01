import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, fail, http, server } from "@/test/api";
import { path, renderApp, screen } from "@/test/app";

describe("app shell", () => {
  it("highlights the section you're in, including nested pages", async () => {
    await renderApp("/agents/new");
    const agents = await screen.findByRole("link", { name: "Agents" });
    expect(agents.getAttribute("data-active")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Firms" }).getAttribute("data-active")).toBeNull();
  });

  it("collapses the sidebar to icons, remembers it, and expands again", async () => {
    const app = await renderApp("/agents");
    await screen.findByRole("link", { name: "Agents" });
    const sidebar = document.querySelector('[data-slot="sidebar"]')!;
    const toggle = document.querySelector<HTMLElement>(
      '[data-slot="sidebar-header"] [data-sidebar="trigger"]',
    )!;
    expect(sidebar.getAttribute("data-state")).toBe("expanded");

    await app.user.click(toggle);
    expect(sidebar.getAttribute("data-state")).toBe("collapsed");
    expect(sidebar.getAttribute("data-collapsible")).toBe("icon");
    expect(document.cookie).toContain("sidebar_state=false");
    screen.getByRole("link", { name: "Agents" }); // still reachable by its icon

    await app.user.click(toggle);
    expect(sidebar.getAttribute("data-state")).toBe("expanded");
    expect(document.cookie).toContain("sidebar_state=true");
  });

  it("opens collapsed when that was the last choice", async () => {
    document.cookie = "sidebar_state=false; path=/";
    await renderApp("/agents");
    await screen.findByRole("link", { name: "Agents" });
    expect(document.querySelector('[data-slot="sidebar"]')!.getAttribute("data-state")).toBe(
      "collapsed",
    );
    document.cookie = "sidebar_state=true; path=/";
  });

  it("toggles the theme and remembers it", async () => {
    document.documentElement.classList.add("dark");
    const app = await renderApp("/registry");
    await app.user.click(await screen.findByRole("button", { name: /Saksham/ }));
    await app.user.click(await screen.findByRole("menuitem", { name: "Light theme" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("lucia-theme")).toBe("light");
  });

  it("signs out to the login page", async () => {
    server.use(http.post(`${API}/auth/logout`, () => new HttpResponse(null, { status: 204 })));
    const app = await renderApp("/registry");
    await app.user.click(await screen.findByRole("button", { name: /Saksham/ }));
    server.use(http.get(`${API}/auth/me`, () => fail(401, "Not authenticated")));
    await app.user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(path(app.router)).toBe("/login"));
  });

  it("an unknown page offers a way back", async () => {
    await renderApp("/nope");
    await screen.findByText("Page not found");
  });
});
