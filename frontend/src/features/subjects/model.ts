import { z } from "zod";

import type { SubjectOut } from "@/api/generated/types.gen";

/** The subject form, mirroring the API's SubjectCreate rules so errors show before sending. */
export const subjectSchema = z.object({
  title: z.string().trim().min(1, "Give it a title").max(200),
  kind: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z0-9 _-]{1,40}$/, "Letters, numbers, spaces, - and _ (up to 40)"),
  external_ref: z.string().trim().max(100),
  status: z.enum(["open", "closed"]),
  description: z.string().max(4000),
});
export type SubjectForm = z.infer<typeof subjectSchema>;

export const blankSubject: SubjectForm = {
  title: "",
  kind: "",
  external_ref: "",
  status: "open",
  description: "",
};

export const toForm = (s: SubjectOut): SubjectForm => ({
  title: s.title,
  kind: s.kind,
  external_ref: s.external_ref ?? "",
  status: s.status === "closed" ? "closed" : "open",
  description: s.description,
});

/** The API's body: an empty reference is "none". */
export const toBody = (f: SubjectForm) => ({ ...f, external_ref: f.external_ref || null });

/** Only the fields that changed, for a PATCH. */
export function changed(before: SubjectForm, after: SubjectForm) {
  const body = toBody(after);
  const was = toBody(before);
  return Object.fromEntries(
    (Object.keys(body) as (keyof typeof body)[])
      .filter((k) => body[k] !== was[k])
      .map((k) => [k, body[k]]),
  );
}
