import { useFormContext } from "react-hook-form";

import { SimpleSelect } from "@/components/shared/controls";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import type { SubjectForm } from "./model";

/** Title, kind (the firm's kinds suggested, any new one allowed), reference, status, notes. */
export function SubjectFields({ kinds }: { kinds: string[] }) {
  const { register, formState, watch, setValue } = useFormContext<SubjectForm>();
  const { errors } = formState;
  return (
    <div className="space-y-4">
      <Field data-invalid={!!errors.title}>
        <FieldLabel htmlFor="subject-title">Title</FieldLabel>
        <Input id="subject-title" placeholder="Doe v. Acme Trucking" {...register("title")} />
        <FieldError errors={[errors.title]} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field data-invalid={!!errors.kind}>
          <FieldLabel htmlFor="subject-kind">Kind</FieldLabel>
          <Input
            id="subject-kind"
            list="subject-kinds"
            autoComplete="off"
            placeholder="matter"
            {...register("kind")}
          />
          <datalist id="subject-kinds">
            {kinds.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
          <FieldError errors={[errors.kind]} />
        </Field>
        <Field>
          <FieldLabel>Status</FieldLabel>
          <SimpleSelect
            label="Status"
            value={watch("status")}
            onChange={(v) => setValue("status", v as SubjectForm["status"], { shouldDirty: true })}
            options={[
              { value: "open", label: "Open" },
              { value: "closed", label: "Closed" },
            ]}
          />
        </Field>
      </div>
      <Field data-invalid={!!errors.external_ref}>
        <FieldLabel htmlFor="subject-ref">External reference</FieldLabel>
        <Input
          id="subject-ref"
          className="font-mono"
          placeholder="DOE-2026-001"
          {...register("external_ref")}
        />
        <FieldError errors={[errors.external_ref]} />
      </Field>
      <Field data-invalid={!!errors.description}>
        <FieldLabel htmlFor="subject-description">Description</FieldLabel>
        <Textarea id="subject-description" rows={3} {...register("description")} />
        <FieldError errors={[errors.description]} />
      </Field>
    </div>
  );
}
