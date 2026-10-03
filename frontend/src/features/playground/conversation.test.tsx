import { waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { API, HttpResponse, http, page, server } from "@/test/api";
import { path, renderApp, screen } from "@/test/app";
import { isDisabled } from "@/test/dom";
import { conversation, linkedRun, message, stepResult } from "@/test/runtime";
import { hold, sse } from "@/test/sse";

import { playgroundApi } from "@/test/playground";

function chat(messages = [message()], events: object[] = []) {
  playgroundApi();
  server.use(
    http.get(`${API}/conversations/c1`, () => HttpResponse.json(conversation())),
    http.get(`${API}/conversations/c1/messages`, () => HttpResponse.json(page(messages))),
    http.get(`${API}/conversations/c1/runs`, () => HttpResponse.json([])),
    http.get(`${API}/conversations/c1/events`, () => sse(events)),
  );
}

const pane = () => screen.findByRole("main", { name: "Conversation" });

describe("conversation", () => {
  it("renders people, the orchestrator and agents differently; agent text as markdown", async () => {
    chat([
      message({ id: "m1", actor: "human", body: "@checkin call Jane" }),
      message({ id: "m2", actor: "system", body: "Started @checkin on Doe v. Acme." }),
      message({
        id: "m3",
        actor: "agent",
        body: "**Jane** is doing better",
        mentions: [],
        agent_id: "a1",
        agent_handle: "sdr",
        run_id: "r1",
      }),
    ]);
    await renderApp("/playground/c1");
    const p = within(await pane());
    expect(
      (await p.findByText("@checkin call Jane"))
        .closest("[data-actor]")
        ?.getAttribute("data-actor"),
    ).toBe("human");
    expect(
      p
        .getByText("Started @checkin on Doe v. Acme.")
        .closest("[data-actor]")
        ?.getAttribute("data-actor"),
    ).toBe("system");
    expect(p.getByText("Jane").tagName).toBe("STRONG");
    p.getByText("@sdr");
    expect(p.queryByText("@agent")).toBeNull();
  });

  it("Enter sends, Shift+Enter adds a line", async () => {
    chat();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/conversations/c1/messages`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(message({ id: "m9" }), { status: 201 });
      }),
    );
    const app = await renderApp("/playground/c1");
    const box = await within(await pane()).findByRole("textbox", { name: "Message" });
    await app.user.type(box, "@checkin first{Shift>}{Enter}{/Shift}second{Enter}");
    await waitFor(() => expect(sent).toEqual([{ body: "@checkin first\nsecond" }]));
  });

  it("replaces the message box with a prompt while a run in the chat waits on an answer", async () => {
    chat([
      message({ id: "m0", actor: "agent", body: "Calling Trevor", run_id: "r1" }),
      message({
        id: "m1",
        actor: "agent",
        body: "Is Lucia SOC 2?",
        run_id: "r1",
        blocks: [{ type: "attention", step_result_id: "q1", kind: "question" }],
      }),
    ]);
    let status = "open";
    server.use(
      http.get(`${API}/runs/r1/attention`, () =>
        HttpResponse.json([stepResult({ id: "q1", run_id: "r1", kind: "question", status })]),
      ),
    );
    const app = await renderApp("/playground/c1");
    const p = within(await pane());
    await p.findByText("Answer the open question above to continue");
    expect(p.queryByRole("textbox", { name: "Message" })).toBeNull();
    status = "answered";
    await app.queryClient.invalidateQueries();
    await p.findByRole("textbox", { name: "Message" });
    expect(p.queryByText("Answer the open question above to continue")).toBeNull();
  });

  it("prompts for a question that arrives after the run's attention was loaded", async () => {
    chat([
      message({
        id: "m1",
        actor: "agent",
        body: "New question",
        run_id: "r1",
        blocks: [{ type: "attention", step_result_id: "q2", kind: "question" }],
      }),
    ]);
    server.use(http.get(`${API}/runs/r1/attention`, () => HttpResponse.json([])));
    await renderApp("/playground/c1");
    await within(await pane()).findByText("Answer the open question above to continue");
  });

  it("a reported finding is read-only and leaves the message box usable", async () => {
    chat([
      message({
        id: "m1",
        actor: "agent",
        body: "No additional callback is authorized",
        run_id: "r1",
        blocks: [{ type: "finding", step_result_id: "f1", urgency: "P1" }],
      }),
      message({
        id: "m2",
        actor: "agent",
        body: "Older finding",
        run_id: "r1",
        blocks: [{ type: "attention", step_result_id: "f2", kind: "finding", free_text: true }],
      }),
    ]);
    server.use(http.get(`${API}/runs/r1/attention`, () => HttpResponse.json([])));
    await renderApp("/playground/c1");
    const p = within(await pane());
    expect(await p.findAllByText(/Reported to the firm/)).toHaveLength(2);
    expect(p.queryByRole("textbox", { name: "Your answer" })).toBeNull();
    await p.findByRole("textbox", { name: "Message" });
  });

  it("@ suggests the firm's agents and inserts the mention", async () => {
    chat();
    const app = await renderApp("/playground/c1");
    const box = await within(await pane()).findByRole("textbox", { name: "Message" });
    await app.user.type(box, "@che");
    await app.user.click(await screen.findByRole("option", { name: /@checkin/ }));
    expect((box as HTMLTextAreaElement).value).toBe("@checkin ");
  });

  it("hints to mention an agent until one is there", async () => {
    chat();
    const app = await renderApp("/playground/c1");
    const p = within(await pane());
    const box = await p.findByRole("textbox", { name: "Message" });
    await app.user.type(box, "call Jane");
    p.getByText(/Mention an agent to start/);
    await app.user.type(box, " @checkin");
    expect(p.queryByText(/Mention an agent to start/)).toBeNull();
  });

  it("the first message creates the chat, then sends it", async () => {
    playgroundApi({ chats: [] });
    const order: string[] = [];
    server.use(
      http.post(`${API}/firms/f1/conversations`, () => {
        order.push("create");
        return HttpResponse.json(conversation({ id: "c7" }), { status: 201 });
      }),
      http.post(`${API}/conversations/c7/messages`, async ({ request }) => {
        order.push(`send:${((await request.json()) as { body: string }).body}`);
        return HttpResponse.json(message({ conversation_id: "c7" }), { status: 201 });
      }),
      http.get(`${API}/conversations/c7`, () => HttpResponse.json(conversation({ id: "c7" }))),
      http.get(`${API}/conversations/c7/messages`, () => HttpResponse.json(page([message()]))),
      http.get(`${API}/conversations/c7/runs`, () => HttpResponse.json([])),
      http.get(`${API}/conversations/c7/events`, () => sse([])),
    );
    const app = await renderApp("/playground");
    await screen.findByText("What can I help you with?");
    await app.user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "@checkin call Jane{Enter}",
    );
    await waitFor(() => expect(path(app.router)).toBe("/playground/c7"));
    expect(order).toEqual(["create", "send:@checkin call Jane"]);
  });

  it("the empty state offers the firm's agents", async () => {
    playgroundApi({ chats: [] });
    const app = await renderApp("/playground");
    await app.user.click(await screen.findByRole("button", { name: /@checkin · Client check-in/ }));
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe(
      "@checkin ",
    );
  });

  it("shows what the orchestrator is doing, and holds the composer meanwhile", async () => {
    const gate = hold();
    playgroundApi();
    server.use(
      http.get(`${API}/conversations/c1`, () => HttpResponse.json(conversation())),
      http.get(`${API}/conversations/c1/messages`, () => HttpResponse.json(page([message()]))),
      http.get(`${API}/conversations/c1/runs`, () => HttpResponse.json([])),
      http.get(`${API}/conversations/c1/events`, () =>
        sse([{ stage: "subject", message_id: "msg1" }], { after: gate.held, event: "progress" }),
      ),
    );
    const app = await renderApp("/playground/c1");
    const p = within(await pane());
    await app.user.type(await p.findByRole("textbox", { name: "Message" }), "@checkin more");
    expect(isDisabled(p.getByRole("button", { name: "Send" }))).toBe(false);
    gate.release();
    await p.findByText("Finding the case…");
    expect(isDisabled(p.getByRole("button", { name: "Send" }))).toBe(true);
  });

  it("lists the run in the header once the chat says it changed", async () => {
    const gate = hold();
    let runs: object[] = [];
    playgroundApi();
    server.use(
      http.get(`${API}/conversations/c1`, () => HttpResponse.json(conversation())),
      http.get(`${API}/conversations/c1/messages`, () => HttpResponse.json(page([message()]))),
      http.get(`${API}/conversations/c1/runs`, () => HttpResponse.json(runs)),
      http.get(`${API}/conversations/c1/events`, () =>
        sse([{}], { after: gate.held, event: "conversation.updated" }),
      ),
    );
    await renderApp("/playground/c1");
    const p = within(await pane());
    const button = await p.findByRole("button", { name: /Agent runs/ });
    expect(isDisabled(button)).toBe(true);
    runs = [linkedRun({ status: "COMPLETED" })];
    gate.release();
    await waitFor(() => expect(isDisabled(button)).toBe(false));
  });

  it("keeps a live run's status fresh in the header", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let status = "ACTIVE";
      chat();
      server.use(
        http.get(`${API}/conversations/c1/runs`, () =>
          HttpResponse.json([linkedRun({ status, substatus: null })]),
        ),
      );
      const app = await renderApp("/playground/c1");
      const p = within(await pane());
      await waitFor(() =>
        expect(isDisabled(p.getByRole("button", { name: /Agent runs/ }))).toBe(false),
      );
      status = "COMPLETED";
      await vi.advanceTimersByTimeAsync(3100);
      await app.user.click(p.getByRole("button", { name: /Agent runs/ }));
      await screen.findByText(/Completed/);
    } finally {
      vi.useRealTimers();
    }
  });
});
