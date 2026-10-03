import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, firm, http, page, server } from "@/test/api";
import { renderApp, screen } from "@/test/app";
import { episode, journal, log, planItem, run, step, task } from "@/test/runtime";

function runWith(plan: Record<string, unknown>[], steps = [step()]) {
  server.use(
    http.get(`${API}/firms`, () => HttpResponse.json(page([firm()]))),
    http.get(`${API}/runs/r1`, () => HttpResponse.json(run())),
    http.get(`${API}/runs/r1/tasks`, () => HttpResponse.json([task({ plan })])),
    http.get(`${API}/runs/r1/episodes`, () => HttpResponse.json([episode()])),
    http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(journal())),
    http.get(`${API}/runs/r1/attention`, () => HttpResponse.json([])),
    http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    http.get(`${API}/runs/r1/steps`, () => HttpResponse.json(steps)),
    http.get(`${API}/runs/r1/logs`, ({ request }) =>
      HttpResponse.json(
        new URL(request.url).searchParams.get("step_id") === "st1"
          ? [log({ message: "Dialing +1555…" })]
          : [],
      ),
    ),
  );
}

async function openSteps() {
  const app = await renderApp("/runs/r1?task=t1");
  const d = within(await screen.findByRole("dialog"));
  await app.user.click(await d.findByRole("tab", { name: /Steps/ }));
  return { app, d };
}

describe("task steps", () => {
  it("strikes through a superseded item and links its replacement", async () => {
    runWith([
      planItem(1, {
        title: "Call Jane",
        status: "SUPERSEDED",
        reason: "email instead",
        superseded_by: ["i2"],
      }),
      planItem(2, { title: "Email Jane", status: "DONE" }),
    ]);
    const { d } = await openSteps();
    const old = (await d.findAllByText("Call Jane")).find((e) => e.closest("ol"))!;
    expect(old.className).toContain("line-through");
    d.getByText("replaced by #2");
  });

  it("a tool item lists its attempts", async () => {
    runWith(
      [planItem(1, { title: "Call Jane", status: "DONE" })],
      [
        step({ id: "st1", seq: 1, status: "SUCCEEDED", output: { ended_reason: "voicemail" } }),
        step({ id: "st2", seq: 2, status: "SUCCEEDED", summary: "Reached Jane" }),
      ],
    );
    const { d } = await openSteps();
    await d.findByText("Attempt 1 · voicemail");
    d.getByText("Attempt 2 · Reached Jane");
  });

  it("a subagent item shows planner → executor → reviewer with the score", async () => {
    runWith(
      [planItem(1, { title: "Summarize", kind: "subagent", tool: null, status: "DONE" })],
      [
        step({ id: "p", kind: "subagent", tool: null, seq: 1 }),
        step({ id: "c1", parent_step_id: "p", kind: "llm", role: "sub_planner", seq: 2 }),
        step({ id: "c2", parent_step_id: "p", kind: "llm", role: "sub_executor", seq: 3 }),
        step({
          id: "c3",
          parent_step_id: "p",
          kind: "llm",
          role: "sub_reviewer",
          seq: 4,
          output: { score: 0.82 },
        }),
      ],
    );
    const { d } = await openSteps();
    await d.findByText("planner → executor → reviewer (0.82)");
  });

  it("details show the policy decision and the key arguments", async () => {
    runWith(
      [planItem(1, { title: "Call Jane", status: "DONE" })],
      [
        step({
          id: "st1",
          input: { to_contact_id: "sc1", script: "Hi" },
          output: { policy: { decision: "allow" } },
          summary: "Call placed",
        }),
      ],
    );
    const { app, d } = await openSteps();
    await app.user.click(await d.findByText("Attempt 1 · Call placed"));
    await d.findByRole("heading", { name: "Step 1: Call Jane" });
    d.getByText("allow");
    d.getByText(/to_contact_id=sc1/);
  });

  it("output shows a call transcript", async () => {
    runWith(
      [planItem(1, { title: "Call Jane", status: "DONE" })],
      [step({ id: "st1", output: { transcript: "AI: Hi Jane\nJane: Hello" } })],
    );
    const { app, d } = await openSteps();
    await app.user.click(await d.findByRole("tab", { name: "Output" }));
    expect((await d.findAllByText(/Jane: Hello/)).length).toBeGreaterThan(0);
  });

  it("logs show the selected step's log lines", async () => {
    runWith([planItem(1, { title: "Call Jane", status: "DONE" })], [step({ id: "st1" })]);
    const { app, d } = await openSteps();
    await app.user.click(await d.findByRole("tab", { name: /^Logs \(/ }));
    await waitFor(() => d.getByText("Dialing +1555…"));
  });
});
