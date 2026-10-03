import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, agentItem, firm, http, page, server } from "@/test/api";
import { path, renderApp, screen } from "@/test/app";
import { isDisabled } from "@/test/dom";
import { journal, run, stepResult, subjectDetail } from "@/test/runtime";

function firmWithRuns(runs = [run()], asked: URLSearchParams[] = []) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/agents`, () => HttpResponse.json(page([agentItem({ handle: "checkin" })]))),
    http.get(`${API}/firms/f1/runs`, ({ request }) => {
      asked.push(new URL(request.url).searchParams);
      return HttpResponse.json(page(runs));
    }),
  );
  return asked;
}

function oneRun(over: Parameters<typeof run>[0] = {}, attention = [stepResult()]) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/runs/r1`, () => HttpResponse.json(run(over))),
    http.get(`${API}/runs/r1/tasks`, () => HttpResponse.json([])),
    http.get(`${API}/runs/r1/episodes`, () => HttpResponse.json([])),
    http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(journal())),
    http.get(`${API}/runs/r1/attention`, () => HttpResponse.json(attention)),
    http.get(`${API}/subjects/subj1`, () => HttpResponse.json(subjectDetail())),
  );
}

describe("agent runs list", () => {
  it("lists the firm's runs with status, tasks and timing", async () => {
    firmWithRuns();
    await renderApp("/runs");
    const row = (await screen.findByText("Doe v. Acme Trucking")).closest("tr")!;
    within(row).getByText("@checkin");
    within(row).getByText("Active");
    within(row).getByText("WAITING");
    within(row).getByText("1/2");
  });

  it("filters by agent, status and subject", async () => {
    const asked = firmWithRuns();
    const app = await renderApp("/runs");
    await screen.findByText("Doe v. Acme Trucking");
    await app.user.type(screen.getByLabelText("Search subjects"), "doe");
    await waitFor(() => expect(asked.at(-1)?.get("q")).toBe("doe"));
    await app.user.click(screen.getByRole("combobox", { name: "Status" }));
    await app.user.click(await screen.findByRole("option", { name: "Taken over" }));
    await waitFor(() => expect(asked.at(-1)?.get("status")).toBe("TAKEN_OVER"));
    await app.user.click(screen.getByRole("combobox", { name: "Agent" }));
    await app.user.click(await screen.findByRole("option", { name: "@checkin" }));
    await waitFor(() => expect(asked.at(-1)?.get("agent")).toBe("checkin"));
  });

  it("opens a run", async () => {
    firmWithRuns();
    oneRun();
    const app = await renderApp("/runs");
    await app.user.click(await screen.findByText("Doe v. Acme Trucking"));
    await waitFor(() => expect(path(app.router)).toBe("/runs/r1"));
  });

  it("no firms yet: points to Firms", async () => {
    await renderApp("/runs");
    await screen.findByText("No firms yet");
    expect(screen.getByRole("link", { name: "Add a firm" }).getAttribute("href")).toBe("/firms");
  });
});

describe("run detail header and controls", () => {
  it("shows the agent, subject, status, goal and criteria", async () => {
    oneRun();
    await renderApp("/runs/r1");
    await screen.findByRole("heading", { name: /@checkin on Doe v. Acme Trucking/ });
    screen.getByText("Check in with Jane");
    screen.getByText("Jane is reached and her update is recorded");
    screen.getByText("v2");
  });

  it("take over needs remarks of 10+ characters", async () => {
    oneRun();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/runs/r1/takeover`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(run({ status: "TAKEN_OVER", substatus: null }));
      }),
    );
    const app = await renderApp("/runs/r1");
    await app.user.click(await screen.findByRole("button", { name: "Take over" }));
    const dialog = within(await screen.findByRole("dialog"));
    const submit = dialog.getByRole("button", { name: "Take over" });
    await app.user.type(dialog.getByLabelText("Remarks"), "too short");
    expect(isDisabled(submit)).toBe(true);
    await app.user.type(dialog.getByLabelText("Remarks"), ", calling her myself");
    await app.user.click(submit);
    await waitFor(() => expect(sent).toEqual([{ remarks: "too short, calling her myself" }]));
  });

  it("a taken-over run shows who holds it and offers hand back", async () => {
    oneRun({
      status: "TAKEN_OVER",
      substatus: null,
      takeover: { by: "u1", remarks: "Calling Jane myself today", at: "2026-10-01T12:00:00Z" },
    });
    await renderApp("/runs/r1");
    await screen.findByText(/Calling Jane myself today/);
    screen.getByRole("button", { name: "Hand back" });
    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
  });

  it("a run paused by repeated failures can be taken over", async () => {
    oneRun({ status: "PAUSED", substatus: "repeated_failure" });
    await renderApp("/runs/r1");
    await screen.findByRole("button", { name: "Take over" });
  });

  it("a finished run has no controls", async () => {
    oneRun({ status: "COMPLETED", substatus: null });
    await renderApp("/runs/r1");
    await screen.findByText("Completed");
    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
  });

  it("awaiting confirmation: confirm in the header", async () => {
    oneRun({ status: "AWAITING_CONFIRMATION", substatus: null }, [
      stepResult({
        id: "sr9",
        kind: "confirm_completion",
        summary: "I think this is done: Jane was reached",
        options: [
          { value: "confirm", label: "Confirm complete" },
          { value: "reopen", label: "Reopen" },
        ],
      }),
    ]);
    await renderApp("/runs/r1");
    await screen.findByText("I think this is done: Jane was reached");
    screen.getAllByRole("button", { name: "Confirm complete" });
  });
});
