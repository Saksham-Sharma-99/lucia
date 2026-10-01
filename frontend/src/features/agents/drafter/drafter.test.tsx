import { waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as sdk from "@/api/generated/sdk.gen";

import {
  API,
  HttpResponse,
  PLATFORM,
  agentDetail,
  agentItem,
  capture,
  fail,
  http,
  page,
  server,
  version,
} from "@/test/api";
import { renderApp, screen } from "@/test/app";
import { isChecked, isDisabled } from "@/test/dom";
import { toast } from "sonner";

import { hold, sse } from "@/test/sse";

// Spy on the generated call (passing through) to see the signal it was given.
vi.mock("@/api/generated/sdk.gen", async (actual) => {
  const mod = await actual<typeof import("@/api/generated/sdk.gen")>();
  return { ...mod, draftAgentPrompt: vi.fn(mod.draftAgentPrompt) };
});

const PROMPT = `${API}/agents/drafts/prompt`;
const SECTION = `${API}/agents/drafts/section`;
const GMAIL = [{ connector: "gmail", tools: ["gmail.send_email"] }];
const NOTE = { rationale: "It emails providers.", unmapped: ["Fax"] };
const RETRY = "Couldn't draft the prompt. Try again.";

type App = Awaited<ReturnType<typeof renderApp>>;
type PromptBody = { instruction: string; current_prompt: string | null; context: object };
type SectionBody = { section: keyof typeof DRAFTS; upstream: Record<string, unknown> };

/** The events of a prompt streamed word by word. */
const written = (text: string) => [
  ...text.split(" ").map((w, i) => ({ type: "delta", text: i ? ` ${w}` : w })),
  { type: "done", prompt: text },
];
/** Serve the prompt stream: one reply per call, the last repeating. Records each request. */
const prompts = (...replies: (() => Response | Promise<Response>)[]) => {
  let call = 0;
  return capture<PromptBody>("post", PROMPT, () => replies[Math.min(call++, replies.length - 1)]());
};

const DRAFTS = {
  capabilities: { section: "capabilities", capabilities: GMAIL, ...NOTE },
  policies: {
    section: "policies",
    policy_pack: [{ rule: "recipient_must_be_contact", params: {} }],
    hitl: { ask_on: ["legal_question"], verify_evidence_below: 0.8 },
    alert_policy: { urgency_mode: "auto", default_channels: { P0: ["email"], P1: [], P2: [] } },
    rationale: "It contacts providers.",
    unmapped: [],
  },
  schedules: {
    section: "schedules",
    follow_up: { mode: "fixed_ladder", ladder: [{ channel: "email", wait_hours: 48 }] },
    recurrence: null,
    end_conditions: { max_duration_days: 120, max_steps: 600, on_subject_closed: "end" },
    max_turns_per_episode: 12,
    rationale: "Email, then wait two days.",
    unmapped: [],
  },
};
/** Serve section drafts (the matching DRAFTS entry, or `reply`). Records each request. */
const sections = (
  reply: (b: SectionBody) => Response | Promise<Response> = (b) =>
    HttpResponse.json(DRAFTS[b.section]),
) => capture<SectionBody>("post", SECTION, reply);

const enabled = () =>
  server.use(
    http.get(`${API}/platform/status`, () =>
      HttpResponse.json({ ...PLATFORM, drafter_enabled: true }),
    ),
  );
const rail = () => within(screen.getByRole("navigation", { name: "Steps" }));
const step = (name: RegExp) => rail().getByRole("button", { name });
const current = () =>
  rail()
    .getAllByRole("button")
    .find((b) => b.getAttribute("aria-current") === "step")?.textContent;
const prompt = () => screen.getByLabelText("System prompt") as HTMLTextAreaElement;
const button = (name: string | RegExp) => screen.getByRole("button", { name });
const next = (app: App) => app.user.click(button("Next"));

/** A blank agent, on the Prompt step. */
async function atPrompt() {
  const app = await renderApp("/agents/new");
  await app.user.click(await screen.findByRole("button", { name: /Blank agent/ }));
  await app.user.type(screen.getByLabelText("Handle"), "chaser");
  await app.user.type(screen.getByLabelText("Name"), "Records chaser");
  await app.user.type(screen.getByLabelText("Description"), "Chases medical records");
  await next(app);
  await screen.findByLabelText("System prompt");
  return app;
}

/** Open the wand, optionally replace its text, and send it. */
async function runWand(app: App, instruction?: string) {
  await app.user.click(button(/with AI/));
  const box = await screen.findByLabelText(/What kind of agent|What should change/);
  if (instruction !== undefined) {
    await app.user.clear(box);
    await app.user.type(box, instruction);
  }
  await app.user.click(button(/^(Write|Refine)$/));
}

/** A blank agent whose prompt the wand wrote, still on the Prompt step. */
async function wandWritten() {
  enabled();
  prompts(() => sse(written("## Role You chase records by email.")));
  const app = await atPrompt();
  await runWand(app);
  await waitFor(() => expect(prompt().value).toContain("You chase records"));
  return app;
}

describe("wizard order", () => {
  it("asks for the prompt before capabilities", async () => {
    await renderApp("/agents/new");
    await screen.findByRole("navigation", { name: "Steps" });
    expect(
      rail()
        .getAllByRole("button")
        .map((b) => b.textContent?.replace(/^\d/, "")),
    ).toEqual([
      "Start",
      "Basic info",
      "Prompt and models",
      "Capabilities",
      "Policies and alerts",
      "Schedules",
      "Review",
    ]);
  });
});

describe("the wand", () => {
  it("is off, with a reason, when drafting isn't configured", async () => {
    const app = await atPrompt();
    const wand = button(/Write with AI/);
    expect(isDisabled(wand)).toBe(true);
    await app.user.hover(wand.parentElement!);
    await screen.findByText("AI drafting isn't configured");
  });

  it("writes the prompt from the description, streaming it in", async () => {
    enabled();
    const sent = prompts(() => sse(written("## Role You chase records.")));
    const app = await atPrompt();
    await app.user.click(button(/Write with AI/));
    const box = (await screen.findByLabelText(
      "What kind of agent is this?",
    )) as HTMLTextAreaElement;
    expect(box.value).toBe("Chases medical records"); // prefilled from Basic info
    await app.user.click(button("Write"));
    await waitFor(() => expect(prompt().value).toBe("## Role You chase records."));
    expect(sent).toEqual([
      {
        instruction: "Chases medical records",
        basic: { name: "Records chaser", description: "Chases medical records", use_cases: [] },
        current_prompt: null,
        context: {}, // a blank agent has nothing else set up yet
      },
    ]);
    expect(button(/Refine with AI/)).toBeTruthy();
  });

  it("needs an instruction; Cmd/Ctrl+Enter sends it", async () => {
    enabled();
    const sent = prompts(() => sse(written("Done.")));
    const app = await atPrompt();
    await app.user.click(button(/Write with AI/));
    const box = await screen.findByLabelText("What kind of agent is this?");
    await app.user.clear(box);
    expect(isDisabled(button("Write"))).toBe(true);
    await app.user.type(box, "   {Control>}{Enter}{/Control}");
    expect(sent).toEqual([]);
    await app.user.type(box, "Chase bills{Control>}{Enter}{/Control}");
    await waitFor(() => expect(prompt().value).toBe("Done."));
    expect(sent).toMatchObject([{ instruction: "Chase bills" }]);
  });

  it("refines the current prompt from an empty box, and Undo puts the old one back", async () => {
    enabled();
    const sent = prompts(() => sse(written("Shorter prompt.")));
    const app = await atPrompt();
    await app.user.type(prompt(), "A long prompt.");
    await app.user.click(button(/Refine with AI/));
    const box = (await screen.findByLabelText("What should change?")) as HTMLTextAreaElement;
    expect(box.value).toBe("");
    await app.user.type(box, "Make it shorter");
    await app.user.click(button("Refine"));
    await waitFor(() => expect(prompt().value).toBe("Shorter prompt."));
    expect(sent[0]).toMatchObject({
      instruction: "Make it shorter",
      current_prompt: "A long prompt.",
    });
    await app.user.click(button(/Undo/));
    expect(prompt().value).toBe("A long prompt.");
    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull();
  });

  it("no Undo once the draft is edited by hand, so edits aren't lost", async () => {
    enabled();
    prompts(() => sse(written("Drafted.")));
    const app = await atPrompt();
    await runWand(app);
    await waitFor(() => expect(prompt().value).toBe("Drafted."));
    expect(button(/Undo/)).toBeTruthy();
    await app.user.type(prompt(), " My edit.");
    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull();
  });

  const HALF = { type: "delta", text: "Half" };
  it.each([
    [
      "the stream reports an error",
      () => sse([HALF, { type: "error", code: "timeout", message: "Too slow" }]),
      "Too slow",
    ],
    ["the connection drops", () => sse([HALF], { broken: true }), RETRY],
    [
      "an event is malformed",
      () => sse([HALF, { type: "delta" }]),
      "The drafter sent something unexpected. Try again.",
    ],
    ["the request is refused", () => fail(503, "AI drafting isn't configured"), RETRY],
  ])("puts the old text back when %s, and doesn't re-send", async (_, reply, message) => {
    enabled();
    const sent = prompts(reply);
    const app = await atPrompt();
    await app.user.type(prompt(), "Mine.");
    await runWand(app, "Redo it");
    await screen.findByText(message);
    expect(prompt().value).toBe("Mine.");
    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull();
    expect(sent).toHaveLength(1);
  });

  it("locks the prompt and the steps while it writes", async () => {
    enabled();
    const gate = hold();
    prompts(() => sse([{ type: "done", prompt: "Done." }], { after: gate.held }));
    const app = await atPrompt();
    await runWand(app);
    await screen.findByRole("button", { name: /Writing…/ });
    for (const el of [prompt(), button("Next"), button("Back"), step(/Basic info/)])
      expect(isDisabled(el)).toBe(true);
    gate.release();
    await waitFor(() => expect(prompt().value).toBe("Done."));
    expect(isDisabled(button("Next"))).toBe(false);
  });

  it("stops the stream when the page is left, and stays quiet after", async () => {
    enabled();
    const gate = hold();
    prompts(() => sse(written("Late."), { after: gate.held }));
    const app = await atPrompt();
    await runWand(app);
    await screen.findByRole("button", { name: /Writing…/ });
    const { signal } = vi.mocked(sdk.draftAgentPrompt).mock.calls[0][0];
    const toastError = vi.spyOn(toast, "error");
    expect(signal?.aborted).toBe(false);
    app.unmount();
    expect(signal?.aborted).toBe(true);
    gate.release();
    await new Promise((r) => setTimeout(r, 20));
    expect(toastError).not.toHaveBeenCalled();
    toastError.mockRestore();
  });
});

describe("setting up the next steps", () => {
  it("doesn't draft anything when the prompt was written by hand", async () => {
    const sent = sections();
    const app = await atPrompt();
    await app.user.type(prompt(), "Chase records.");
    await next(app);
    await waitFor(() => expect(current()).toMatch(/Capabilities/));
    expect(sent).toEqual([]);
  });

  it("drafts each step once, from the prompt and the steps before it", async () => {
    const sent = sections();
    const app = await wandWritten();
    await next(app);
    await screen.findByText(NOTE.rationale);
    screen.getByText("Couldn't set up: Fax");
    expect(sent[0]).toMatchObject({
      section: "capabilities",
      system_prompt: "## Role You chase records by email.",
      basic: { name: "Records chaser" },
      upstream: {},
    });

    await next(app);
    await screen.findByText("It contacts providers.");
    expect(screen.queryByText(/Couldn't set up/)).toBeNull(); // nothing unmapped
    expect(sent[1].upstream).toEqual({ capabilities: GMAIL });

    await next(app);
    await screen.findByText("Email, then wait two days.");
    expect(Object.keys(sent[2].upstream).sort()).toEqual([
      "alert_policy",
      "capabilities",
      "hitl",
      "policy_pack",
    ]);
    expect(sent[2].upstream.policy_pack).toEqual(DRAFTS.policies.policy_pack);

    // Back and forth never drafts again.
    await app.user.click(step(/Capabilities/));
    for (let i = 0; i < 3; i++) await next(app); // Capabilities -> Review
    expect(current()).toMatch(/Review/);
    expect(sent.map((s) => s.section)).toEqual(["capabilities", "policies", "schedules"]);
  });

  it("drafts over a template's steps too, once the wand is used", async () => {
    enabled();
    server.use(
      http.get(`${API}/agents`, () => HttpResponse.json(page([agentItem({ is_template: true })]))),
      http.get(`${API}/agents/records`, () =>
        HttpResponse.json(agentDetail({ is_template: true })),
      ),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
    );
    const sentPrompts = prompts(() => sse(written("Refined.")));
    const READ_ONLY = [{ connector: "gmail", tools: ["gmail.read_thread"] }];
    sections(() => HttpResponse.json({ ...DRAFTS.capabilities, capabilities: READ_ONLY }));
    const app = await renderApp("/agents/new?template=records");
    await app.user.type(await screen.findByLabelText("Handle"), "chaser");
    await next(app);
    await runWand(app, "Warmer");
    await waitFor(() => expect(prompt().value).toBe("Refined."));
    expect(sentPrompts[0].context).toMatchObject({ capabilities: GMAIL }); // the template's
    await next(app);
    await screen.findByText(NOTE.rationale);
    expect(isChecked(screen.getByRole("checkbox", { name: /read_thread/ }))).toBe(true);
    expect(isChecked(screen.getByRole("checkbox", { name: /send_email/ }))).toBe(false);
  });

  it("refining later sends the steps set up so far as context", async () => {
    sections();
    const app = await wandWritten();
    const sent = prompts(() => sse(written("Warmer.")));
    await next(app);
    await screen.findByText(NOTE.rationale);
    await app.user.click(button("Back"));
    await runWand(app, "Warmer");
    await waitFor(() => expect(prompt().value).toBe("Warmer."));
    expect(sent[0].context).toEqual({ capabilities: GMAIL });
  });

  it("leaves a step the person reached before using the wand", async () => {
    const sent = sections();
    enabled();
    prompts(() => sse(written("Drafted.")));
    const app = await atPrompt();
    await app.user.type(prompt(), "By hand.");
    await next(app); // Capabilities, set up by hand
    await waitFor(() => expect(current()).toMatch(/Capabilities/));
    await app.user.click(button("Back"));
    await runWand(app, "Redo");
    await waitFor(() => expect(prompt().value).toBe("Drafted."));
    await next(app);
    await waitFor(() => expect(current()).toMatch(/Capabilities/));
    expect(screen.queryByText("Drafting from your prompt…")).toBeNull();
    await app.user.click(screen.getByRole("checkbox", { name: /^GMAIL/ })); // by hand
    await next(app); // Policies, never reached before
    await screen.findByText("It contacts providers.");
    expect(sent.map((b) => b.section)).toEqual(["policies"]);
  });

  it("the note can be dismissed", async () => {
    sections();
    const app = await wandWritten();
    await next(app);
    await screen.findByText(NOTE.rationale);
    await app.user.click(button("Dismiss note"));
    expect(screen.queryByText(NOTE.rationale)).toBeNull();
  });

  it("locks navigation while it drafts, and a double click drafts once", async () => {
    const gate = hold();
    const sent = sections(async (b) => {
      await gate.held;
      return HttpResponse.json(DRAFTS[b.section]);
    });
    const app = await wandWritten();
    await app.user.dblClick(button("Next"));
    await screen.findByText("Drafting from your prompt…");
    for (const el of [button("Next"), button("Back"), step(/Basic info/)])
      expect(isDisabled(el)).toBe(true);
    gate.release();
    await screen.findByText(NOTE.rationale);
    expect(isDisabled(button("Next"))).toBe(false);
    expect(current()).toMatch(/Capabilities/);
    expect(sent).toHaveLength(1);
  });

  it.each([
    [
      "the drafter fails",
      () => fail(504, "The drafter took too long. Try again."),
      /took too long/,
    ],
    ["the network fails", () => HttpResponse.error(), /Couldn't draft this step/],
  ])("when %s: says so, keeps the step's values, never retries", async (_, reply, message) => {
    const sent = sections(reply);
    const app = await wandWritten();
    await next(app);
    await screen.findByText(message);
    expect(screen.queryByText("Drafting from your prompt…")).toBeNull();
    expect(screen.queryByText("Drafted from your prompt")).toBeNull();
    expect(isChecked(screen.getByRole("checkbox", { name: /^GMAIL/ }))).toBe(false);
    await app.user.click(button("Back"));
    await next(app);
    expect(sent).toHaveLength(1);
  });
});

describe("amend", () => {
  const amend = () => {
    server.use(
      http.get(`${API}/agents/records`, () => HttpResponse.json(agentDetail())),
      http.get(`${API}/agents/records/versions/1`, () => HttpResponse.json(version())),
    );
    return renderApp("/agents/records/amend?from=1");
  };

  it("refines the prompt with the whole config as context, and never drafts the tabs", async () => {
    enabled();
    const sent = prompts(() => sse(written("Refined.")));
    const sectionSent = sections();
    const app = await amend();
    await app.user.click(await screen.findByRole("tab", { name: /Prompt and models/ }));
    await runWand(app, "Warmer");
    await waitFor(() => expect(prompt().value).toBe("Refined."));
    expect(sent[0]).toMatchObject({
      instruction: "Warmer",
      current_prompt: "Chase records.",
      basic: { name: "Medical Records Follow-up" },
    });
    expect(Object.keys(sent[0].context)).toEqual(
      expect.arrayContaining(["capabilities", "policy_pack", "follow_up", "max_turns_per_episode"]),
    );
    for (const tab of [/Capabilities/, /Policies/, /Schedules/])
      await app.user.click(screen.getByRole("tab", { name: tab }));
    expect(sectionSent).toEqual([]);
  });

  it("can't save while the wand writes", async () => {
    enabled();
    const gate = hold();
    prompts(() => sse([{ type: "done", prompt: "New." }], { after: gate.held }));
    const app = await amend();
    await app.user.click(await screen.findByRole("tab", { name: /Prompt and models/ }));
    await runWand(app, "Warmer");
    await screen.findByRole("button", { name: /Writing…/ });
    expect(isDisabled(button(/Save as v2/))).toBe(true);
    gate.release();
    await waitFor(() => expect(prompt().value).toBe("New."));
    await app.user.type(screen.getByLabelText("What changed"), "Warmer prompt");
    expect(isDisabled(button(/Save as v2/))).toBe(false);
  });
});
