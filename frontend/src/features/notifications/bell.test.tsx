import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, http, server } from "@/test/api";
import { path, renderApp, screen, search } from "@/test/app";
import { notification } from "@/test/runtime";

const bell = () => screen.findByRole("button", { name: /Notifications/ });

describe("notification bell", () => {
  it("shows the unread count", async () => {
    server.use(
      http.get(`${API}/notifications`, () =>
        HttpResponse.json([
          notification(),
          notification({ id: "n2" }),
          notification({ id: "n3", read_at: "2026-10-01T12:00:00Z" }), // read: not counted
        ]),
      ),
    );
    await renderApp("/agents");
    await waitFor(async () => expect((await bell()).textContent).toContain("2"));
  });

  it("opening one marks it read and goes to the run's attention", async () => {
    const read: string[] = [];
    server.use(
      http.get(`${API}/notifications`, () => HttpResponse.json([notification()])),
      http.post(`${API}/notifications/:id/read`, ({ params }) => {
        read.push(params.id as string);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const app = await renderApp("/agents");
    await app.user.click(await bell());
    const list = await screen.findByRole("dialog");
    await app.user.click(within(list).getByText(/needs your input/));
    await waitFor(() => expect(path(app.router)).toBe("/runs/r1"));
    expect(search(app.router).tab).toBe("attention");
    expect(read).toEqual(["n1"]);
  });

  it("marks all read", async () => {
    let cleared = false;
    server.use(
      http.get(`${API}/notifications`, () => HttpResponse.json(cleared ? [] : [notification()])),
      http.post(`${API}/notifications/read-all`, () => {
        cleared = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const app = await renderApp("/agents");
    await app.user.click(await bell());
    await app.user.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(async () => expect((await bell()).textContent).not.toContain("1"));
  });

  it("nothing new", async () => {
    const app = await renderApp("/agents");
    await app.user.click(await bell());
    await screen.findByText("You're all caught up");
  });
});
