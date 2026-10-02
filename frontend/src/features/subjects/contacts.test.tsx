import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, fail, firm, firmDetail, http, page, server } from "@/test/api";
import { renderApp, screen } from "@/test/app";
import { contactPoint, subject, subjectContact, subjectDetail } from "@/test/runtime";

function setup(detail = subjectDetail(), others = [contactPoint({ id: "cp2", name: "Dr. Lee" })]) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail())),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/subject-kinds`, () => HttpResponse.json(["matter"])),
    http.get(`${API}/firms/f1/subjects`, () => HttpResponse.json(page([subject()]))),
    http.get(`${API}/firms/f1/contact-points`, () => HttpResponse.json(page(others))),
    http.get(`${API}/subjects/subj1`, () => HttpResponse.json(detail)),
  );
}

const open = async () => {
  const app = await renderApp("/firms/f1?tab=subjects&subject=subj1");
  const d = within(await screen.findByRole("dialog"));
  await d.findByText("Jane Doe");
  return { app, d };
};

describe("subject contacts", () => {
  it("shows the contact's details", async () => {
    setup();
    const { d } = await open();
    d.getByText("client");
    d.getByText("+15551234567");
    d.getByText("jane@example.com");
    d.getByText("America/New_York");
  });

  it("records consent per channel", async () => {
    setup();
    const sent: unknown[] = [];
    server.use(
      http.patch(`${API}/subject-contacts/sc1`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(subjectContact());
      }),
    );
    const { app, d } = await open();
    await app.user.click(d.getByRole("radio", { name: "Voice consent: refused" }));
    await waitFor(() => expect(sent).toEqual([{ consent: { voice: "refused" } }]));
  });

  it("clearing an opt-out needs a reason", async () => {
    setup(
      subjectDetail({
        contacts: [
          subjectContact({ contact_point: contactPoint({ opt_out: { voice: {}, email: {} } }) }),
        ],
      }),
    );
    const sent: unknown[] = [];
    server.use(
      http.patch(`${API}/contact-points/cp1`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(contactPoint());
      }),
    );
    const { app, d } = await open();
    d.getByText("Opted out: voice");
    await app.user.click(d.getByRole("button", { name: "Clear voice opt-out" }));
    const confirm = within(await screen.findByRole("alertdialog"));
    const ok = confirm.getByRole("button", { name: "Clear opt-out" });
    await app.user.click(ok);
    expect(sent).toEqual([]);
    await app.user.type(confirm.getByLabelText("Reason"), "She asked us to call again");
    await app.user.click(ok);
    await waitFor(() =>
      expect(sent).toEqual([{ opt_out: ["email"], reason: "She asked us to call again" }]),
    );
  });

  it("removes a contact from the subject", async () => {
    setup();
    let deleted = false;
    server.use(
      http.delete(`${API}/subject-contacts/sc1`, () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { app, d } = await open();
    await app.user.click(d.getByRole("button", { name: "Remove Jane Doe" }));
    await app.user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Remove" }),
    );
    await waitFor(() => expect(deleted).toBe(true));
  });

  it("links an existing contact with a role", async () => {
    setup();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/subjects/subj1/contacts`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(subjectContact(), { status: 201 });
      }),
    );
    const { app, d } = await open();
    await app.user.click(d.getByRole("button", { name: "Add contact" }));
    const add = within(await screen.findByRole("dialog", { name: "Add contact" }));
    await app.user.click(await add.findByRole("button", { name: /Dr. Lee/ }));
    await app.user.click(add.getByRole("combobox", { name: "Role" }));
    await app.user.click(await screen.findByRole("option", { name: "provider" }));
    await app.user.click(add.getByRole("button", { name: "Add to subject" }));
    await waitFor(() => expect(sent).toEqual([{ contact_point_id: "cp2", role: "provider" }]));
  });

  it("creates a new contact, then links it", async () => {
    setup(subjectDetail(), []);
    const order: string[] = [];
    server.use(
      http.post(`${API}/firms/f1/contact-points`, async ({ request }) => {
        order.push(`create:${JSON.stringify(await request.json())}`);
        return HttpResponse.json(contactPoint({ id: "cp9", name: "Sam Roe" }), { status: 201 });
      }),
      http.post(`${API}/subjects/subj1/contacts`, async ({ request }) => {
        order.push(`link:${JSON.stringify(await request.json())}`);
        return HttpResponse.json(subjectContact(), { status: 201 });
      }),
    );
    const { app, d } = await open();
    await app.user.click(d.getByRole("button", { name: "Add contact" }));
    const add = within(await screen.findByRole("dialog", { name: "Add contact" }));
    await app.user.click(add.getByRole("tab", { name: "New contact" }));
    await app.user.type(add.getByLabelText("Name"), "Sam Roe");
    await app.user.type(add.getByLabelText("Phone"), "+15559876543");
    await app.user.click(add.getByRole("button", { name: "Add to subject" }));
    await waitFor(() => expect(order).toHaveLength(2));
    expect(order[0]).toContain('"name":"Sam Roe"');
    expect(order[0]).toContain('"e164":"+15559876543"');
    expect(order[1]).toBe('link:{"contact_point_id":"cp9","role":"client"}');
  });

  it("shows the server's error on a bad phone number", async () => {
    setup(subjectDetail(), []);
    server.use(
      http.post(`${API}/firms/f1/contact-points`, () =>
        fail(422, "Validation failed", [
          { path: "/phones/0/e164", code: "pattern", message: "Use +country format" },
        ]),
      ),
    );
    const { app, d } = await open();
    await app.user.click(d.getByRole("button", { name: "Add contact" }));
    const add = within(await screen.findByRole("dialog", { name: "Add contact" }));
    await app.user.click(add.getByRole("tab", { name: "New contact" }));
    await app.user.type(add.getByLabelText("Name"), "Sam Roe");
    await app.user.type(add.getByLabelText("Phone"), "555");
    await app.user.click(add.getByRole("button", { name: "Add to subject" }));
    await add.findByText("Use +country format");
  });
});
