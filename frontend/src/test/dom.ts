import { screen } from "@testing-library/react";

/** Base UI marks disabled controls with `disabled`, `aria-disabled` or `data-disabled`. */
export const isDisabled = (el: Element) =>
  (el as HTMLButtonElement).disabled ||
  el.getAttribute("aria-disabled") === "true" ||
  el.hasAttribute("data-disabled");

/** Base UI switches and checkboxes report their state through `aria-checked`. */
export const isChecked = (el: Element) => el.getAttribute("aria-checked") === "true";

/** The number under a StatCards label, e.g. stat("Ready") → "3". */
export const stat = (label: string) =>
  screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
