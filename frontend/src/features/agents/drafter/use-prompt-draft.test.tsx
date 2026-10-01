import { renderHook, waitFor } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { API, capture } from "@/test/api";
import { hold, sse } from "@/test/sse";

import { blankConfig } from "../config";
import { usePromptDraft } from "./use-prompt-draft";

describe("usePromptDraft", () => {
  it("runs one draft at a time", async () => {
    const gate = hold();
    const sent = capture("post", `${API}/agents/drafts/prompt`, () =>
      sse([{ type: "done", prompt: "Done." }], { after: gate.held }),
    );
    const { result } = renderHook(() => {
      const form = useForm({ defaultValues: { config: blankConfig(["m"]) } });
      return { form, draft: usePromptDraft(form, { basic: () => ({}), context: () => ({}) }) };
    });
    void result.current.draft.start("First");
    void result.current.draft.start("Second"); // ignored: one is in flight
    await waitFor(() => expect(sent).toHaveLength(1));
    gate.release();
    await waitFor(() =>
      expect(result.current.form.getValues("config.system_prompt")).toBe("Done."),
    );
    expect(sent).toMatchObject([{ instruction: "First" }]);
  });
});
