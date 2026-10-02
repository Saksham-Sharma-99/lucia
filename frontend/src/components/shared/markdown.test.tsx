import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

describe("Markdown", () => {
  it("renders model text: bold, lists, links in a new tab", () => {
    render(<Markdown>{"**Jane** is better\n\n- started PT\n- [notes](https://x.test)"}</Markdown>);
    expect(screen.getByText("Jane").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "notes" }).getAttribute("target")).toBe("_blank");
  });

  it("never renders raw HTML from the model", () => {
    const { container } = render(<Markdown>{"<img src=x onerror=alert(1)> hi"}</Markdown>);
    expect(container.querySelector("img")).toBeNull();
  });
});
