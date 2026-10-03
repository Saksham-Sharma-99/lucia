import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, firm, http, page, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { episode, journal, planItem, run, stepResult, task } from "@/test/runtime";

function runWith({
  tasks = [task()],
  episodes = [episode()],
  entries = journal(),
  attention = [stepResult()],
} = {}) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/runs/r1`, () => HttpResponse.json(run())),
    http.get(`${API}/runs/r1/tasks`, () => HttpResponse.json(tasks)),
    http.get(`${API}/runs/r1/episodes`, () => HttpResponse.json(episodes)),
    http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(entries)),
    http.get(`${API}/runs/r1/attention`, () => HttpResponse.json(attention)),
    http.get(`${API}/runs/r1/steps`, () => HttpResponse.json([])),
  );
}

const column = (label: string) => screen.getByRole("region", { name: new RegExp(`^${label}`) });

describe("run tabs", () => {
  it("lays tasks out by status; failed sits with skipped", async () => {
    runWith({
      tasks: [
        task({ id: "t1", title: "Call Jane", status: "WAITING" }),
        task({ id: "t2", key: "summary:run", title: "Write summary", status: "FAILED" }),
        task({ id: "t3", key: "records:run", title: "Get records", status: "DONE" }),
      ],
    });
    await renderApp("/runs/r1");
    await screen.findByText("Call Jane");
    within(column("Waiting")).getByText("Call Jane");
    within(column("Skipped")).getByText("Write summary");
    within(column("Done")).getByText("Get records");
  });

  it("a card shows its items progress and a waiting-on dependency", async () => {
    runWith({
      tasks: [
        task({ id: "t1", key: "records:run", title: "Get records", status: "IN_PROGRESS" }),
        task({
          id: "t2",
          title: "Call Jane",
          status: "TODO",
          depends_on: ["records:run"],
          plan: [
            planItem(1, { status: "DONE" }),
            planItem(2),
            planItem(3, { status: "SUPERSEDED" }),
          ],
        }),
      ],
    });
    await renderApp("/runs/r1");
    const card = (await screen.findByText("Call Jane")).closest("button")!;
    within(card).getByText("1/2 items");
    within(card).getByLabelText("Waiting on records:run");
  });

  it("clicking a task opens it", async () => {
    runWith();
    const app = await renderApp("/runs/r1");
    await app.user.click(await screen.findByText("Call Jane"));
    await waitFor(() => expect(search(app.router).task).toBe("t1"));
  });

  it("episodes: newest first, with trigger, outcome and due time", async () => {
    runWith({
      episodes: [
        episode({
          id: "e2",
          trigger_type: "scheduled",
          source: "ladder",
          status: "scheduled",
          due_at: "2026-10-03T12:00:00Z",
          outcome: null,
          created_at: "2026-10-02T12:00:00Z",
        }),
        episode({
          id: "e1",
          trigger_type: "user_input",
          outcome: "triaged",
          created_at: "2026-10-01T12:00:00Z",
        }),
      ],
    });
    await renderApp("/runs/r1?tab=episodes");
    const items = within(await screen.findByRole("list", { name: "Episodes" })).getAllByRole(
      "listitem",
    );
    expect(items[0].textContent).toContain("Scheduled · ladder");
    expect(items[0].textContent).toContain("due");
    expect(items[1].textContent).toContain("User input");
    expect(items[1].textContent).toContain("triaged");
  });

  it("journal: summary then entries with their source", async () => {
    runWith({
      entries: journal({
        summary: "Jane was reached twice.",
        entries: [
          {
            id: "j1",
            task_id: "t1",
            episode_id: null,
            source: "harness",
            text: "Call Jane: reached",
            created_at: "2026-10-01T12:00:00Z",
          },
        ],
      }),
    });
    await renderApp("/runs/r1?tab=journal");
    await screen.findByText("Jane was reached twice.");
    screen.getByText("Call Jane: reached");
    screen.getByText("harness");
  });

  it("attention: open items first, answerable", async () => {
    runWith({
      attention: [
        stepResult({
          id: "a1",
          summary: "Old question",
          status: "answered",
          answer: { choice: null, text: "done" },
        }),
        stepResult({
          id: "a2",
          summary: "Which number?",
          options: [{ value: "m", label: "Mobile" }],
        }),
      ],
    });
    await renderApp("/runs/r1?tab=attention");
    const cards = await screen.findAllByText(/question|number/i);
    expect(cards[0].textContent).toBe("Which number?");
    screen.getByRole("button", { name: "Mobile" });
  });
});
