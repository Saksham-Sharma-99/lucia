import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, firm, http, page, server } from "@/test/api";
import { renderApp, screen } from "@/test/app";
import { episode, journal, log, planItem, run, step, task } from "@/test/runtime";

function runWith(asked: URLSearchParams[] = []) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/runs/r1`, () => HttpResponse.json(run())),
    http.get(`${API}/runs/r1/tasks`, () =>
      HttpResponse.json([
        task({
          plan: [
            planItem(1, {
              title: "Draft script",
              kind: "subagent",
              tool: null,
              status: "DONE",
              output: { summary: "Hi Jane…" },
            }),
            planItem(2, { title: "Call Jane", status: "DONE", output: { summary: "Reached" } }),
          ],
          output: { summary: "Jane is better", evidence_step_ids: ["st1"] },
        }),
      ]),
    ),
    http.get(`${API}/runs/r1/episodes`, () =>
      HttpResponse.json([episode({ reason: null, source: null })]),
    ),
    http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(journal())),
    http.get(`${API}/runs/r1/attention`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/runs/r1/steps`, () =>
      HttpResponse.json([
        step({
          id: "sa",
          plan_item_id: "i1",
          kind: "subagent",
          tool: null,
          input: { what: "a script" },
          output: { artifact: "Hi Jane…" },
        }),
        step({
          id: "pl",
          seq: 0,
          kind: "llm",
          role: "planner",
          tool: null,
          plan_item_id: null,
          model: "gpt-5.6-sol",
          input: { message: "Plan the check-in call" },
          output: { items: ["Draft script", "Call Jane"] },
          input_tokens: 812,
          output_tokens: 96,
        }),
        step({
          id: "ex",
          seq: 2,
          kind: "llm",
          role: "executor",
          tool: null,
          plan_item_id: "i2",
          input: { message: "Fill the call arguments" },
          output: { script: "Ask about PT" },
        }),
        step({
          id: "st1",
          seq: 3,
          plan_item_id: "i2",
          input: { to_contact_id: "sc1" },
          output: {
            transcript: "AI: Hi Jane, how are you?\nUser: Much better,\nthanks.",
            ended_reason: "customer-ended-call",
          },
        }),
        step({
          id: "sm",
          seq: 4,
          kind: "llm",
          role: "summarizer",
          tool: null,
          plan_item_id: "i2",
          input: { message: "Summarize the call" },
          output: { text: "Jane is better" },
        }),
      ]),
    ),
    http.get(`${API}/runs/r1/steps/st1/recording`, () =>
      HttpResponse.json({ url: "https://storage.vapi.ai/call-1.wav?sig=x" }),
    ),
    http.get(`${API}/runs/r1/logs`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      asked.push(q);
      return HttpResponse.json([
        log({ id: "l1", level: "info", stage: "executor", message: "Calling Jane" }),
        log({
          id: "l2",
          level: "debug",
          stage: "planner",
          step_id: "pl",
          message: "Planned 2 items",
        }),
      ]);
    }),
  );
  return asked;
}

async function openTab(name: string) {
  const app = await renderApp("/runs/r1?task=t1");
  const d = within(await screen.findByRole("dialog"));
  await app.user.click(await d.findByRole("tab", { name }));
  return { app, d };
}

describe("task logs", () => {
  it("lists the task's logs and filters by level and text on the server", async () => {
    const asked = runWith();
    const { app, d } = await openTab("Logs");
    await d.findByText("Calling Jane");
    await app.user.click(d.getByRole("combobox", { name: "Level" }));
    await app.user.click(await screen.findByRole("option", { name: "warn" }));
    await waitFor(() => expect(asked.at(-1)?.get("level")).toBe("warn"));
    await app.user.type(d.getByLabelText("Search logs"), "Jane");
    await waitFor(() => expect(asked.at(-1)?.get("q")).toBe("Jane"));
    expect(asked.at(-1)?.get("task_id")).toBe("t1");
  });

  it("filters by stage on the page", async () => {
    runWith();
    const { app, d } = await openTab("Logs");
    await d.findByText("Calling Jane");
    await app.user.click(d.getByRole("combobox", { name: "Stage" }));
    await app.user.click(await screen.findByRole("option", { name: "planner" }));
    await waitFor(() => expect(d.queryByText("Calling Jane")).toBeNull());
    d.getByText("Planned 2 items");
  });

  it("expands a line into what the model was asked and what it answered", async () => {
    runWith();
    const { app, d } = await openTab("Logs");
    await app.user.click(await d.findByRole("button", { name: /Planned 2 items/ }));
    await d.findByText("Plan the check-in call");
    d.getByText(/"Draft script"/);
    d.getByText(/812 in \/ 96 out/);
    await app.user.click(d.getByRole("button", { name: /Planned 2 items/ }));
    await waitFor(() => expect(d.queryByText("Plan the check-in call")).toBeNull());
  });

  it("a call's line shows its transcript", async () => {
    runWith();
    const { app, d } = await openTab("Logs");
    await app.user.click(await d.findByRole("button", { name: /Calling Jane/ }));
    await d.findByText("Hi Jane, how are you?");
  });
});

describe("call transcript and recording", () => {
  it("shows the call as turns and plays a fresh recording link", async () => {
    runWith();
    const { app, d } = await openTab("Inputs & Outputs");
    await app.user.click(await d.findByRole("button", { name: "Voice (Vapi)" }));
    const turns = await d.findAllByRole("listitem", { name: /^(Agent|Contact)$/ });
    expect(turns.map((t) => t.textContent)).toEqual([
      "AgentHi Jane, how are you?",
      "ContactMuch better, thanks.",
    ]);
    await app.user.click(d.getByRole("button", { name: "Play recording" }));
    const audio = await waitFor(() => {
      const el = d.getByLabelText("Call recording");
      expect(el.getAttribute("src")).toBe("https://storage.vapi.ai/call-1.wav?sig=x");
      return el;
    });
    expect(audio.tagName).toBe("AUDIO");
  });

  it("says so when Vapi has no recording", async () => {
    runWith();
    server.use(
      http.get(`${API}/runs/r1/steps/st1/recording`, () =>
        HttpResponse.json({ title: "Not found", status: 404 }, { status: 404 }),
      ),
    );
    const { app, d } = await openTab("Inputs & Outputs");
    await app.user.click(await d.findByRole("button", { name: "Voice (Vapi)" }));
    await app.user.click(await d.findByRole("button", { name: "Play recording" }));
    await d.findByText("No recording for this call.");
  });
});

describe("task inputs and outputs", () => {
  it("lists every model call in order, with the tool calls between them", async () => {
    runWith();
    const { app, d } = await openTab("Inputs & Outputs");
    await app.user.click(await d.findByRole("button", { name: "Subagent input" }));
    const calls = await d.findAllByRole("article");
    expect(calls.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Planner",
      "Subagent",
      "Executor · fills the tool's arguments",
      "Summarizer",
    ]);
    within(calls[2]).getByText("Fill the call arguments");
    d.getByText(/then Voice \(Vapi\) · place_call/);
    await app.user.click(d.getByRole("button", { name: "Subagent output" }));
    await d.findByText(/"script": "Ask about PT"/);
    d.getByText("Jane is better", { selector: "pre" });
  });

  it("navigates the sections", async () => {
    runWith();
    const { app, d } = await openTab("Inputs & Outputs");
    await d.findByRole("heading", { name: "User input" });
    await app.user.click(d.getByRole("button", { name: "Subagent input" }));
    await d.findByText(/"what": "a script"/);
    await app.user.click(d.getByRole("button", { name: "Subagent output" }));
    await d.findByText(/"artifact": "Hi Jane…"/);
    await app.user.click(d.getByRole("button", { name: "Voice (Vapi)" }));
    await d.findByText(/"to_contact_id": "sc1"/);
    await app.user.click(d.getByRole("button", { name: "Intermediate data" }));
    await d.findByText("Reached");
    await app.user.click(d.getByRole("button", { name: "Final output" }));
    await d.findByText("Jane is better", { selector: "p" });
  });
});
