import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, connection, firm, http, page, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { episode, journal, planItem, run, step, task } from "@/test/runtime";

const DONE_TASK = task({
  status: "DONE",
  ended_at: "2026-10-01T12:00:20Z",
  plan: [
    planItem(1, { title: "Call Jane", status: "DONE", tool: "vapi.place_call" }),
    planItem(2, { title: "Journal it", status: "DONE", tool: "harness.journal_append" }),
  ],
  output: { summary: "**Jane** is doing better", evidence_step_ids: ["st1"] },
});

function runWith(
  tasks = [DONE_TASK, task({ id: "t2", key: "records:run", title: "Get records" })],
) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/runs/r1`, () => HttpResponse.json(run())),
    http.get(`${API}/runs/r1/tasks`, () => HttpResponse.json(tasks)),
    http.get(`${API}/runs/r1/episodes`, () =>
      HttpResponse.json([
        episode({ trigger_type: "user_input", reason: null, created_at: "2026-10-01T11:00:00Z" }),
      ]),
    ),
    http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(journal())),
    http.get(`${API}/runs/r1/attention`, () => HttpResponse.json([])),
    http.get(`${API}/runs/r1/logs`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/connections`, () =>
      HttpResponse.json([connection({ connector: "vapi", status: "connected" })]),
    ),
    http.get(`${API}/runs/r1/steps`, ({ request }) => {
      const taskId = new URL(request.url).searchParams.get("task_id");
      return HttpResponse.json(
        taskId
          ? [step(), step({ id: "st2", seq: 2 })]
          : [
              step({
                id: "s9",
                task_id: null,
                plan_item_id: null,
                kind: "llm",
                role: "triage",
                tool: null,
                summary: "Planned the call",
              }),
              step(),
            ],
      );
    }),
  );
}

const drawer = () => screen.findByRole("dialog");

describe("task drawer", () => {
  it("opens on a task with its title, status and a task selector", async () => {
    runWith();
    await renderApp("/runs/r1?task=t1");
    const d = within(await drawer());
    await d.findByRole("heading", { name: "Call Jane" });
    expect(d.getAllByText("Done").length).toBeGreaterThan(0);
    d.getByRole("combobox", { name: "Task" });
  });

  it("switching the task updates the URL", async () => {
    runWith();
    const app = await renderApp("/runs/r1?task=t1");
    const d = within(await drawer());
    await app.user.click(await d.findByRole("combobox", { name: "Task" }));
    await app.user.click(await screen.findByRole("option", { name: /Get records/ }));
    await waitFor(() => expect(search(app.router).task).toBe("t2"));
  });

  it("the Run view lists the run's own steps (triage, completion)", async () => {
    runWith();
    const app = await renderApp("/runs/r1?task=t1");
    const d = within(await drawer());
    await app.user.click(await d.findByRole("button", { name: "Run" }));
    await d.findByText("Planned the call");
    d.getByText("triage");
  });

  it("overview: trigger, task, agent, connectors with counts, and the output", async () => {
    runWith();
    await renderApp("/runs/r1?task=t1");
    const d = within(await drawer());
    const flow = within(await d.findByRole("region", { name: "How this task ran" }));
    flow.getByText("User input");
    flow.getByText("Find out how Jane is doing");
    flow.getByText("@checkin");
    flow.getByText("Voice (Vapi)");
    await flow.findByText("Connected");
    flow.getByLabelText("2 calls");
    expect(flow.getByText("Jane").tagName).toBe("STRONG");
    expect(flow.queryByText(/harness/i)).toBeNull();
    const rail = within(d.getByRole("complementary", { name: "Task details" }));
    rail.getByText("call-client:contact-1");
    rail.getByText("2/2");
  });

  it("overview: each round and its items in the flow; what happened beside them", async () => {
    runWith([
      task({
        plan: [
          planItem(1, { title: "Call Jane", status: "DONE" }),
          planItem(2, { title: "Send the summary", status: "PENDING", added_in: 1, tool: null }),
        ],
      }),
    ]);
    server.use(
      http.get(`${API}/runs/r1/episodes`, () =>
        HttpResponse.json([
          episode({
            id: "e1",
            created_at: "2026-10-01T11:00:00Z",
            started_at: "2026-10-01T11:00:00Z",
          }),
          episode({
            id: "e2",
            task_id: "t1",
            trigger_type: "external_response",
            outcome: "reached",
            created_at: "2026-10-01T12:10:00Z",
            started_at: "2026-10-01T12:10:00Z",
          }),
        ]),
      ),
      http.get(`${API}/runs/r1/steps`, () =>
        HttpResponse.json([
          step({
            id: "p1",
            seq: 0,
            kind: "llm",
            role: "planner",
            tool: null,
            plan_item_id: null,
            started_at: "2026-10-01T11:00:30Z",
          }),
          step({ id: "c1", episode_id: "e1", started_at: "2026-10-01T11:01:00Z" }),
          step({
            id: "p2",
            seq: 2,
            kind: "llm",
            role: "planner",
            tool: null,
            plan_item_id: null,
            started_at: "2026-10-01T12:10:40Z",
          }),
          step({
            id: "s2",
            seq: 3,
            kind: "subagent",
            tool: "harness.subagent",
            plan_item_id: "i2",
            episode_id: "e2",
            started_at: "2026-10-01T12:11:00Z",
          }),
        ]),
      ),
      http.get(`${API}/runs/r1/journal`, () =>
        HttpResponse.json(
          journal({
            entries: [
              {
                id: "j1",
                task_id: "t1",
                episode_id: "e2",
                source: "harness",
                text: "Jane is better",
                created_at: "2026-10-01T12:10:30Z",
              },
            ],
          }),
        ),
      ),
    );
    await renderApp("/runs/r1?task=t1");
    const flow = within(
      await within(await drawer()).findByRole("region", { name: "How this task ran" }),
    );
    await flow.findByText("Added");
    expect(flow.getAllByText("1 item")).toHaveLength(2); // the first plan and the append
    await flow.findByText("Jane is better"); // the journal entry, beside the item running then
    const notes = flow.getAllByRole("list", { name: "What happened" }).map((n) => n.textContent);
    expect(notes).toEqual([
      expect.stringContaining("Plan written"),
      expect.stringContaining("Call placed"),
      expect.stringMatching(/Episode arrived.*External response.*Plan revised/),
      expect.stringMatching(/Journal entry created.*Jane is better.*Subagent wrote a draft/),
    ]);
    flow.getByText("Send the summary");
  });

  it("View output opens the final output", async () => {
    runWith();
    const app = await renderApp("/runs/r1?task=t1");
    const d = within(await drawer());
    await app.user.click(await d.findByRole("button", { name: /View output/ }));
    await waitFor(() =>
      expect(d.getByRole("tab", { name: "Inputs & Outputs" }).getAttribute("aria-selected")).toBe(
        "true",
      ),
    );
    await d.findByRole("heading", { name: "Final output" });
  });

  it("closes", async () => {
    runWith();
    const app = await renderApp("/runs/r1?task=t1");
    await app.user.click(await within(await drawer()).findByRole("button", { name: "Close" }));
    await waitFor(() => expect(search(app.router).task).toBeUndefined());
  });
});
