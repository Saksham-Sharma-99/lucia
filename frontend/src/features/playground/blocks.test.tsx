import { waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { API, HttpResponse, http, page, server } from "@/test/api";
import { renderApp, screen, search } from "@/test/app";
import { playgroundApi } from "@/test/playground";
import {
  conversation,
  journal,
  linkedRun,
  message,
  run,
  stepResult,
  subjectDetail,
  task,
} from "@/test/runtime";
import { sse } from "@/test/sse";

function chatWith(
  blocks: Record<string, unknown>[],
  over: Parameters<typeof conversation>[0] = {},
  msg: Parameters<typeof message>[0] = {},
) {
  playgroundApi();
  const actions: unknown[] = [];
  server.use(
    http.get(`${API}/conversations/c1`, () => HttpResponse.json(conversation(over))),
    http.get(`${API}/conversations/c1/messages`, () =>
      HttpResponse.json(
        page([message({ id: "m1", actor: "system", body: "Which case?", blocks, ...msg })]),
      ),
    ),
    http.get(`${API}/conversations/c1/runs`, () => HttpResponse.json([linkedRun()])),
    http.get(`${API}/conversations/c1/events`, () => sse([])),
    http.post(`${API}/conversations/c1/actions`, async ({ request }) => {
      actions.push(await request.json());
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return actions;
}

const pane = async () => within(await screen.findByRole("main", { name: "Conversation" }));

describe("message blocks", () => {
  it("subject picker: pick one, or none", async () => {
    const actions = chatWith(
      [
        {
          type: "subject_picker",
          options: [{ subject_id: "subj1", title: "Doe v. Acme Trucking", kind: "matter" }],
          allow_none: true,
        },
      ],
      { pending: { kind: "subject_pick", message_id: "m1", options: ["subj1"] } },
    );
    const app = await renderApp("/playground/c1");
    const p = await pane();
    await app.user.click(await p.findByRole("button", { name: /Doe v. Acme Trucking/ }));
    await waitFor(() =>
      expect(actions).toEqual([{ type: "subject_pick", value: "subj1", message_id: "m1" }]),
    );
    await app.user.click(p.getByRole("button", { name: "None of these" }));
    await waitFor(() => expect(actions[1]).toMatchObject({ value: "none" }));
  });

  it("an answered picker is closed and says what was picked", async () => {
    chatWith(
      [{ type: "subject_picker", options: [{ subject_id: "subj1", title: "Doe v. Acme" }] }],
      { pending: null, subject_id: "subj1", subject_title: "Doe v. Acme Trucking" },
    );
    await renderApp("/playground/c1");
    const p = await pane();
    await p.findByText("Picked: Doe v. Acme Trucking");
    expect(p.queryByRole("button", { name: "None of these" })).toBeNull();
  });

  it("agent suggestion: use the suggested agent", async () => {
    const actions = chatWith(
      [
        {
          type: "agent_suggestion",
          mentioned: "checkin",
          suggested: [{ handle: "liens", score: 0.9, reason: "lien work" }],
        },
      ],
      { pending: { kind: "agent_suggest", message_id: "m1" } },
    );
    const app = await renderApp("/playground/c1");
    await app.user.click(await (await pane()).findByRole("button", { name: "Use @liens" }));
    await waitFor(() =>
      expect(actions).toEqual([{ type: "agent_suggest", value: "liens", message_id: "m1" }]),
    );
  });

  it("retry re-runs the message", async () => {
    const actions = chatWith([{ type: "retry", message_id: "m1" }]);
    const app = await renderApp("/playground/c1");
    await app.user.click(await (await pane()).findByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(actions).toEqual([{ type: "retry", value: null, message_id: "m1" }]),
    );
  });

  it("an attention card shows its state from the run", async () => {
    chatWith(
      [
        {
          type: "attention",
          step_result_id: "sr1",
          kind: "question",
          options: [],
          free_text: true,
        },
      ],
      {},
      { actor: "agent", run_id: "r1", body: "Which number should I call?" },
    );
    server.use(
      http.get(`${API}/runs/r1/attention`, () =>
        HttpResponse.json([
          stepResult({ status: "answered", answer: { choice: null, text: "Mobile" } }),
        ]),
      ),
    );
    await renderApp("/playground/c1");
    await (await pane()).findByText("Answered: Mobile");
  });

  it("an unknown block renders nothing; the message still shows", async () => {
    chatWith([{ type: "hologram", foo: 1 }]);
    await renderApp("/playground/c1");
    await (await pane()).findByText("Which case?");
  });

  it("a run link opens the task drawer over the chat", async () => {
    chatWith([{ type: "run_link", run_id: "r1", agent: "checkin" }]);
    server.use(
      http.get(`${API}/runs/r1`, () => HttpResponse.json(run())),
      http.get(`${API}/runs/r1/tasks`, () => HttpResponse.json([task()])),
      http.get(`${API}/runs/r1/steps`, () => HttpResponse.json([])),
      http.get(`${API}/runs/r1/episodes`, () => HttpResponse.json([])),
      http.get(`${API}/runs/r1/journal`, () => HttpResponse.json(journal())),
      http.get(`${API}/firms/f1/connections`, () => HttpResponse.json([])),
    );
    const app = await renderApp("/playground/c1");
    await app.user.click(await (await pane()).findByRole("button", { name: /@checkin/ }));
    await waitFor(() => expect(search(app.router).drawer).toBe("r1"));
    await within(await screen.findByRole("dialog")).findByRole("heading", { name: "Call Jane" });
  });
});

describe("chat header", () => {
  it("the subject chip opens the subject read-only", async () => {
    chatWith([], { subject_id: "subj1", subject_title: "Doe v. Acme Trucking" });
    server.use(http.get(`${API}/subjects/subj1`, () => HttpResponse.json(subjectDetail())));
    const app = await renderApp("/playground/c1");
    await app.user.click(await screen.findByRole("button", { name: /Doe v. Acme Trucking/ }));
    const d = within(await screen.findByRole("dialog"));
    await d.findByText("Jane Doe");
    expect(d.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("the agent runs menu lists the chat's runs", async () => {
    chatWith([]);
    const app = await renderApp("/playground/c1");
    const menu = await screen.findByRole("button", { name: /Agent runs/ });
    await waitFor(() => expect(menu.hasAttribute("disabled")).toBe(false));
    await app.user.click(menu);
    await screen.findByRole("menuitem", { name: /@checkin · Active · 1\/2 tasks done/ });
  });
});
