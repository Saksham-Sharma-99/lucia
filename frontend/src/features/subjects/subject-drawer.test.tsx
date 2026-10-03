import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, fail, firm, firmDetail, http, page, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { subject, subjectDetail } from "@/test/runtime";

function firmAndSubject(detail = subjectDetail()) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail())),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/subject-kinds`, () => HttpResponse.json(["matter"])),
    http.get(`${API}/firms/f1/subjects`, () => HttpResponse.json(page([subject()]))),
    http.get(`${API}/firms/f1/contact-points`, () => HttpResponse.json(page([]))),
    http.get(`${API}/subjects/subj1`, () => HttpResponse.json(detail)),
  );
}

const drawer = () => screen.findByRole("dialog");

describe("subject drawer", () => {
  it("creates a subject and opens it", async () => {
    firmAndSubject();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/firms/f1/subjects`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(subjectDetail(), { status: 201 });
      }),
    );
    const app = await renderApp("/firms/f1?tab=subjects&subject=new");
    const d = within(await drawer());
    await app.user.type(d.getByLabelText("Title"), "Doe v. Acme Trucking");
    await app.user.type(d.getByLabelText("Kind"), "Matter");
    await app.user.type(d.getByLabelText("External reference"), "DOE-2026-001");
    await app.user.click(d.getByRole("button", { name: "Create subject" }));
    await waitFor(() => expect(search(app.router).subject).toBe("subj1"));
    expect(sent[0]).toMatchObject({
      title: "Doe v. Acme Trucking",
      kind: "matter",
      external_ref: "DOE-2026-001",
      status: "open",
    });
  });

  it("puts the server's field error under the field", async () => {
    firmAndSubject();
    server.use(
      http.post(`${API}/firms/f1/subjects`, () =>
        fail(422, "Validation failed", [
          { path: "/external_ref", code: "taken", message: "External ref is taken" },
        ]),
      ),
    );
    const app = await renderApp("/firms/f1?tab=subjects&subject=new");
    const d = within(await drawer());
    await app.user.type(d.getByLabelText("Title"), "Doe");
    await app.user.type(d.getByLabelText("Kind"), "matter");
    await app.user.type(d.getByLabelText("External reference"), "DOE-2026-001");
    await app.user.click(d.getByRole("button", { name: "Create subject" }));
    await d.findByText("External ref is taken");
  });

  it("edits only what changed", async () => {
    firmAndSubject();
    const sent: unknown[] = [];
    server.use(
      http.patch(`${API}/subjects/subj1`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(subjectDetail({ title: "Doe v. Acme (settled)" }));
      }),
    );
    const app = await renderApp("/firms/f1?tab=subjects&subject=subj1");
    const d = within(await drawer());
    await app.user.click(await d.findByRole("button", { name: "Edit" }));
    const title = d.getByLabelText("Title");
    await app.user.clear(title);
    await app.user.type(title, "Doe v. Acme (settled)");
    await app.user.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent).toEqual([{ title: "Doe v. Acme (settled)" }]));
  });

  it("lists the subject's runs with links", async () => {
    firmAndSubject();
    await renderApp("/firms/f1?tab=subjects&subject=subj1");
    const d = within(await drawer());
    const link = await d.findByRole("link", { name: /@checkin/ });
    expect(link.getAttribute("href")).toBe("/runs/r1");
  });

  it("closes back to the list", async () => {
    firmAndSubject();
    const app = await renderApp("/firms/f1?tab=subjects&subject=subj1");
    await drawer();
    await app.user.keyboard("{Escape}");
    await waitFor(() => expect(search(app.router).subject).toBeUndefined());
  });
});
