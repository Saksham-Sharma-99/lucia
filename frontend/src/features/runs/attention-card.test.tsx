import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import { API, HttpResponse, fail, http, server } from "@/test/api";
import { renderWithClient, screen } from "@/test/app";
import { isDisabled } from "@/test/dom";
import { stepResult } from "@/test/runtime";

import { AttentionCard } from "./attention-card";

const options = [{ value: "mobile", label: "Mobile" }];

describe("AttentionCard", () => {
  it("answers with an option", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/attention/sr1/answer`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(stepResult({ status: "answered" }));
      }),
    );
    const app = renderWithClient(<AttentionCard item={stepResult({ options })} />);
    await app.user.click(screen.getByRole("button", { name: "Mobile" }));
    await waitFor(() => expect(sent).toEqual([{ choice: "mobile", text: null }]));
  });

  it("a question can be answered in free text", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/attention/sr1/answer`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(stepResult({ status: "answered" }));
      }),
    );
    const app = renderWithClient(<AttentionCard item={stepResult()} />);
    await app.user.type(screen.getByLabelText("Your answer"), "Her mobile, ends 4567");
    await app.user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sent).toEqual([{ choice: null, text: "Her mobile, ends 4567" }]));
  });

  it("a goal that can't be met offers ending the run, or telling the agent what to do", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/attention/sr1/answer`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(stepResult({ status: "answered" }));
      }),
    );
    const item = stepResult({
      summary: "Goal not met and no next step: Saksham declined",
      options: [{ value: "end_run", label: "End the run" }],
    });
    const app = renderWithClient(<AttentionCard item={item} />);
    screen.getByLabelText("Your answer");
    await app.user.click(screen.getByRole("button", { name: "End the run" }));
    await waitFor(() => expect(sent).toEqual([{ choice: "end_run", text: null }]));
  });

  it("reopening a finished run needs a note", async () => {
    const item = stepResult({
      kind: "confirm_completion",
      options: [
        { value: "confirm", label: "Confirm complete" },
        { value: "reopen", label: "Reopen" },
      ],
    });
    const app = renderWithClient(<AttentionCard item={item} />);
    await app.user.click(screen.getByRole("button", { name: "Reopen…" }));
    expect(isDisabled(screen.getByRole("button", { name: "Send" }))).toBe(true);
    await app.user.type(screen.getByLabelText("What's still needed?"), "Send her the forms");
    expect(isDisabled(screen.getByRole("button", { name: "Send" }))).toBe(false);
  });

  it("an answered item shows the answer and no buttons", () => {
    renderWithClient(
      <AttentionCard
        item={stepResult({ status: "answered", answer: { choice: "mobile", text: null }, options })}
      />,
    );
    screen.getByText("Answered: Mobile");
    expect(screen.queryByRole("button", { name: "Mobile" })).toBeNull();
  });

  it("someone else answered first: says so", async () => {
    server.use(
      http.post(`${API}/attention/sr1/answer`, () => fail(409, "This item was already answered")),
    );
    const info = vi.spyOn(toast, "info");
    const app = renderWithClient(<AttentionCard item={stepResult({ options })} />);
    await app.user.click(screen.getByRole("button", { name: "Mobile" }));
    await vi.waitFor(() => expect(info).toHaveBeenCalledWith("Already answered"));
  });
});
