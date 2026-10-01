import { describe, expect, it } from "vitest";

import { API, HttpResponse, capture, fail, http, server, user } from "@/test/api";
import { path, renderApp, screen, search } from "@/test/app";

const signedOut = http.get(`${API}/auth/me`, () => fail(401, "Not authenticated"));

async function signIn(app: Awaited<ReturnType<typeof renderApp>>, password = "pw") {
  await app.user.type(await screen.findByLabelText("Username"), "saksham");
  await app.user.type(screen.getByLabelText("Password"), password);
  await app.user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("auth guard", () => {
  it("sends a signed-out visitor to /login, remembering where they were going", async () => {
    server.use(signedOut);
    const app = await renderApp("/firms");
    await screen.findByRole("heading", { name: "Sign in to Studio" });
    expect(path(app.router)).toBe("/login");
    expect(search(app.router).redirect).toContain("/firms");
  });

  it("lets a signed-in user straight through", async () => {
    const app = await renderApp("/firms");
    await screen.findByRole("heading", { name: "Firms" });
    expect(path(app.router)).toBe("/firms");
  });
});

describe("login page", () => {
  it("signs in and returns to the redirect target", async () => {
    let signedIn = false;
    server.use(
      http.get(`${API}/auth/me`, () =>
        signedIn ? HttpResponse.json(user()) : fail(401, "Not authenticated"),
      ),
      http.post(`${API}/auth/login`, async ({ request }) => {
        expect(request.headers.get("x-requested-with")).toBe("lucia");
        signedIn = true;
        return HttpResponse.json(user());
      }),
    );
    const app = await renderApp("/login?redirect=%2Fregistry");
    await signIn(app);
    await screen.findByRole("heading", { name: "Registry" });
    expect(path(app.router)).toBe("/registry");
  });

  it.each([
    [401, "Username or password is incorrect."],
    [429, "Too many failed attempts. Wait 15 minutes and try again."],
  ])("explains a %i", async (status, message) => {
    server.use(
      signedOut,
      http.post(`${API}/auth/login`, () => fail(status, "nope")),
    );
    const app = await renderApp("/login");
    await signIn(app, "wrong");
    expect((await screen.findByRole("alert")).textContent).toBe(message);
  });

  it("explains an unreachable server", async () => {
    server.use(
      signedOut,
      http.post(`${API}/auth/login`, () => HttpResponse.error()),
    );
    const app = await renderApp("/login");
    await signIn(app);
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Could not reach the server. Try again.",
    );
  });

  it("requires both fields before calling the API", async () => {
    server.use(signedOut);
    const called = capture("post", `${API}/auth/login`, () => HttpResponse.json(user()));
    const app = await renderApp("/login");
    await app.user.click(await screen.findByRole("button", { name: "Sign in" }));
    await screen.findByText("Enter your username");
    screen.getByText("Enter your password");
    expect(called).toHaveLength(0);
  });
});
