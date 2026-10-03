import { useFormContext } from "react-hook-form";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

import type { ContactForm } from "./contact-form";

/** Name, organisation, phone, email, timezone: shared by every contact form. */
export function ContactFields() {
  const { register, formState } = useFormContext<ContactForm>();
  const { errors } = formState;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field data-invalid={!!errors.name}>
          <FieldLabel htmlFor="contact-name">Name</FieldLabel>
          <Input id="contact-name" {...register("name", { required: "Give a name" })} />
          <FieldError errors={[errors.name]} />
        </Field>
        <Field data-invalid={!!errors.org_name}>
          <FieldLabel htmlFor="contact-org">Organisation</FieldLabel>
          <Input id="contact-org" placeholder="Optional" {...register("org_name")} />
          <FieldError errors={[errors.org_name]} />
        </Field>
      </div>
      <Field data-invalid={!!errors.phones?.[0]?.e164}>
        <FieldLabel htmlFor="contact-phone">Phone</FieldLabel>
        <Input
          id="contact-phone"
          className="font-mono"
          placeholder="+15551234567"
          {...register("phones.0.e164")}
        />
        <FieldError errors={[errors.phones?.[0]?.e164]} />
      </Field>
      <Field data-invalid={!!errors.emails?.[0]}>
        <FieldLabel htmlFor="contact-email">Email</FieldLabel>
        <Input id="contact-email" type="email" {...register("emails.0")} />
        <FieldError errors={[errors.emails?.[0]]} />
      </Field>
      <Field data-invalid={!!errors.tz}>
        <FieldLabel htmlFor="contact-tz">Timezone</FieldLabel>
        <Input id="contact-tz" placeholder="America/New_York" {...register("tz")} />
        <FieldError errors={[errors.tz]} />
      </Field>
      {errors.root && (
        <p role="alert" className="text-destructive text-sm">
          {errors.root.message}
        </p>
      )}
    </div>
  );
}
