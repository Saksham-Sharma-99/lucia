import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";

import type { Problem } from "@/api/generated/types.gen";

export function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && "status" in value && "title" in value;
}

/** `/config/capabilities/1/tools/0` -> `config.capabilities.1.tools.0` */
export function pointerToField(path: string): string {
  return path.replace(/^\//, "").split("/").join(".");
}

export function problemMessage(error: unknown): string {
  if (isProblem(error)) return error.detail || error.title;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

/**
 * Put each field error on its form field; returns the errors that matched no field.
 * `fields` lists the form's field paths (or prefixes) so unknown paths become toasts.
 */
export function applyFieldErrors<T extends FieldValues>(
  setError: UseFormSetError<T>,
  error: unknown,
  isField: (name: string) => boolean = () => true,
  /** A prefix the server uses that the form doesn't, e.g. "settings." for a settings form. */
  strip = "",
): string[] {
  if (!isProblem(error) || !error.errors?.length) return [problemMessage(error)];
  const unmatched: string[] = [];
  for (const e of error.errors) {
    const name = pointerToField(e.path).replace(strip, "");
    if (name && isField(name)) setError(name as Path<T>, { type: e.code, message: e.message });
    else unmatched.push(e.message);
  }
  return unmatched;
}

export function toastError(error: unknown, prefix?: string) {
  const message = problemMessage(error);
  toast.error(prefix ? `${prefix}: ${message}` : message);
}

/** For dialogs and forms: field errors on their fields, everything else as the form's root error. */
export function showFormErrors<T extends FieldValues>(
  setError: UseFormSetError<T>,
  error: unknown,
) {
  const rest = applyFieldErrors(setError, error);
  if (rest.length) setError("root" as Path<T>, { message: rest.join(" ") });
}
