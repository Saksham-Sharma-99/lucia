import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, fail, firm, firmDetail, http, page, server } from "@/test/api";
import { renderApp, screen } from "@/test/app";
import { contactPoint } from "@/test/runtime";

function firmWithContacts(contacts = [contactPoint()], asked: URLSearchParams[] = []) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/firms/f1`, () => HttpResponse.json(firmDetail())),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/contact-points`, ({ request }) => {
      asked.push(new URL(request.url).searchParams);
      return HttpResponse.json(page(contacts));
    }),
  );
  return asked;
}

describe("firm contacts tab", () => {
  it("comes after Subjects and lists the firm's contacts", async () => {
    firmWithContacts([contactPoint({ opt_out: { voice: {} }, org_name: "Self" })]);
    await renderApp("/firms/f1?tab=contacts");
    const tabs = (await screen.findAllByRole("tab")).map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Settings", "Connections", "Subjects", "Contacts"]);
    const row = (await screen.findByText("Jane Doe")).closest("tr")!;
    within(row).getByText("+15551234567");
    within(row).getByText("jane@example.com");
    within(row).getByText("America/New_York");
    within(row).getByText("voice");
  });

  it("shows each contact's type: its roles on the firm's subjects", async () => {
    firmWithContacts([
      contactPoint({ roles: ["client", "provider"] }),
      contactPoint({ id: "cp2", name: "Walk-in", roles: [] }),
    ]);
    await renderApp("/firms/f1?tab=contacts");
    const jane = (await screen.findByText("Jane Doe")).closest("tr")!;
    screen.getByRole("columnheader", { name: "Type" });
    within(jane).getByText("client");
    within(jane).getByText("provider");
    within(screen.getByText("Walk-in").closest("tr")!).getByText("Not on a subject");
  });

  it("searches name, email or phone", async () => {
    const asked = firmWithContacts();
    const app = await renderApp("/firms/f1?tab=contacts");
    await screen.findByText("Jane Doe");
    await app.user.type(screen.getByLabelText("Search contacts"), "5551234");
    await waitFor(() => expect(asked.at(-1)?.get("q")).toBe("5551234"));
  });

  it("adds a contact", async () => {
    firmWithContacts([]);
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/firms/f1/contact-points`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(contactPoint(), { status: 201 });
      }),
    );
    const app = await renderApp("/firms/f1?tab=contacts");
    await app.user.click((await screen.findAllByRole("button", { name: /New contact/ }))[0]);
    const d = within(await screen.findByRole("dialog"));
    await app.user.type(d.getByLabelText("Name"), "Jane Doe");
    await app.user.type(d.getByLabelText("Phone"), "+15551234567");
    await app.user.click(d.getByRole("button", { name: "Save contact" }));
    await waitFor(() =>
      expect(sent).toEqual([
        { name: "Jane Doe", phones: [{ e164: "+15551234567" }], emails: [], tz: null },
      ]),
    );
  });

  it("edits a contact, showing the server's field errors", async () => {
    firmWithContacts();
    let attempt = 0;
    const sent: unknown[] = [];
    server.use(
      http.patch(`${API}/contact-points/cp1`, async ({ request }) => {
        sent.push(await request.json());
        return ++attempt === 1
          ? fail(422, "Validation failed", [
              { path: "/tz", code: "invalid", message: "Unknown timezone" },
            ])
          : HttpResponse.json(contactPoint({ tz: "America/Chicago" }));
      }),
    );
    const app = await renderApp("/firms/f1?tab=contacts");
    await app.user.click(await screen.findByRole("button", { name: "Edit Jane Doe" }));
    const d = within(await screen.findByRole("dialog"));
    const tz = d.getByLabelText("Timezone");
    await app.user.clear(tz);
    await app.user.type(tz, "Mars/Base");
    await app.user.click(d.getByRole("button", { name: "Save contact" }));
    await d.findByText("Unknown timezone");
    await app.user.clear(tz);
    await app.user.type(tz, "America/Chicago");
    await app.user.click(d.getByRole("button", { name: "Save contact" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ tz: "America/Chicago" });
  });

  it("empty firm", async () => {
    firmWithContacts([]);
    await renderApp("/firms/f1?tab=contacts");
    await screen.findByText("No contacts yet");
  });
});
