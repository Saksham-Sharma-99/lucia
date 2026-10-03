import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, firm, firmDetail, http, page, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { subject, subjectDetail } from "@/test/runtime";

function firmWith(subjects = [subject()], asked: URLSearchParams[] = []) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail())),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/subject-kinds`, () => HttpResponse.json(["matter", "lead"])),
    http.get(`${API}/firms/f1/subjects`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      asked.push(q);
      return HttpResponse.json(page(subjects));
    }),
  );
  return asked;
}

describe("firm subjects tab", () => {
  it("comes after Connections and shows subject cards", async () => {
    firmWith();
    await renderApp("/firms/f1?tab=subjects");
    const tabs = (await screen.findAllByRole("tab")).map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Settings", "Connections", "Subjects", "Contacts"]);
    await screen.findByText("Doe v. Acme Trucking");
    screen.getByText("DOE-2026-001");
    screen.getByText("1 contact");
    screen.getByText("1 live run");
  });

  it("filters by search, kind and status", async () => {
    const asked = firmWith();
    const app = await renderApp("/firms/f1?tab=subjects");
    await screen.findByText("Doe v. Acme Trucking");
    await app.user.type(screen.getByLabelText("Search subjects"), "doe");
    await waitFor(() => expect(asked.at(-1)?.get("q")).toBe("doe"));
    await app.user.click(screen.getByRole("button", { name: "lead" }));
    await waitFor(() => expect(asked.at(-1)?.get("kind")).toBe("lead"));
    await app.user.click(screen.getByRole("button", { name: "Closed" }));
    await waitFor(() => expect(asked.at(-1)?.get("status")).toBe("closed"));
  });

  it("opens a new subject, or an existing one", async () => {
    firmWith();
    server.use(http.get(`${API}/subjects/subj1`, () => HttpResponse.json(subjectDetail())));
    const app = await renderApp("/firms/f1?tab=subjects");
    await app.user.click((await screen.findAllByRole("button", { name: /New subject/ }))[0]);
    await waitFor(() => expect(search(app.router).subject).toBe("new"));
    await app.user.keyboard("{Escape}");
    await waitFor(() => expect(search(app.router).subject).toBeUndefined());
    await app.user.click(await screen.findByText("Doe v. Acme Trucking"));
    await waitFor(() => expect(search(app.router).subject).toBe("subj1"));
  });

  it("empty firm: invites the first subject", async () => {
    firmWith([]);
    await renderApp("/firms/f1?tab=subjects");
    await screen.findByText("No subjects yet");
  });
});
