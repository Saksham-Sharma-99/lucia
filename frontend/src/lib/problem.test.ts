import { describe, expect, it, vi } from "vitest";

import { applyFieldErrors, isProblem, pointerToField, problemMessage } from "./problem";

const problem = (
  errors: { path: string; code: string; message: string }[] = [],
  detail = "Bad",
) => ({
  type: "about:blank",
  title: "Unprocessable entity",
  status: 422,
  detail,
  errors,
});

describe("pointerToField", () => {
  it.each([
    ["/config/capabilities/1/tools/0", "config.capabilities.1.tools.0"],
    ["/handle", "handle"],
    ["", ""],
    ["/", ""],
  ])("%s -> %s", (path, field) => expect(pointerToField(path)).toBe(field));
});

describe("isProblem / problemMessage", () => {
  it("recognises problem+json bodies only", () => {
    expect(isProblem(problem())).toBe(true);
    expect(isProblem({ status: 422 })).toBe(false);
    expect(isProblem(null)).toBe(false);
    expect(isProblem("error")).toBe(false);
  });

  it("prefers detail, then title, then Error message", () => {
    expect(problemMessage(problem([], "Handle is taken"))).toBe("Handle is taken");
    expect(problemMessage({ ...problem(), detail: undefined })).toBe("Unprocessable entity");
    expect(problemMessage(new Error("offline"))).toBe("offline");
    expect(problemMessage(42)).toBe("Something went wrong");
  });
});

describe("applyFieldErrors", () => {
  it("sets matched fields and returns the rest", () => {
    const setError = vi.fn();
    const left = applyFieldErrors(
      setError,
      problem([
        {
          path: "/config/models/loop",
          code: "model_not_allowed",
          message: "Model x is not allowed",
        },
        { path: "/unknown", code: "x", message: "Elsewhere" },
      ]),
      (name) => name.startsWith("config."),
    );
    expect(setError).toHaveBeenCalledWith("config.models.loop", {
      type: "model_not_allowed",
      message: "Model x is not allowed",
    });
    expect(left).toEqual(["Elsewhere"]);
  });

  it("returns the message when there are no field errors", () => {
    const setError = vi.fn();
    expect(applyFieldErrors(setError, problem([], "Conflict happened"))).toEqual([
      "Conflict happened",
    ]);
    expect(applyFieldErrors(setError, new Error("network"))).toEqual(["network"]);
    expect(setError).not.toHaveBeenCalled();
  });

  it("treats a root pointer as unmatched", () => {
    const setError = vi.fn();
    expect(
      applyFieldErrors(setError, problem([{ path: "", code: "x", message: "Whole body" }])),
    ).toEqual(["Whole body"]);
  });
});
