import type { ContactPointCreate, ContactPointOut } from "@/api/generated/types.gen";

/** The contact form: one phone and one email, the common case (the API takes lists). */
export type ContactForm = {
  name: string;
  org_name: string;
  phones: { e164: string }[];
  emails: string[];
  tz: string;
};

export const blankContact: ContactForm = {
  name: "",
  org_name: "",
  phones: [{ e164: "" }],
  emails: [""],
  tz: "",
};

export const contactToForm = (cp: ContactPointOut): ContactForm => ({
  name: cp.name,
  org_name: cp.org_name ?? "",
  phones: [{ e164: (cp.phones[0] as { e164?: string } | undefined)?.e164 ?? "" }],
  emails: [cp.emails[0] ?? ""],
  tz: cp.tz ?? "",
});

/** The API body; blanks are dropped (an empty org isn't sent at all). */
export function contactBody(v: ContactForm): ContactPointCreate {
  const body: ContactPointCreate = {
    name: v.name.trim(),
    phones: v.phones.filter((p) => p.e164.trim()).map((p) => ({ e164: p.e164.trim() })),
    emails: v.emails.map((e) => e.trim()).filter(Boolean),
    tz: v.tz.trim() || null,
  };
  return v.org_name.trim() ? { ...body, org_name: v.org_name.trim() } : body;
}
