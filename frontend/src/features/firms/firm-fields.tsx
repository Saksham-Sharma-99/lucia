import { Controller, useFormContext } from "react-hook-form";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

import { FIRM_COLORS, type FirmDetails } from "./model";

const ZONES: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "UTC"];
  }
})();

/** Name, timezone and colour: shared by the new-firm dialog and the firm's Overview. */
export function FirmFields({ onNameChange }: { onNameChange?: (name: string) => void }) {
  const { register, control, formState } = useFormContext<FirmDetails>();
  const { errors } = formState;
  const name = register("name");
  return (
    <>
      <Field className="max-w-md" data-invalid={!!errors.name}>
        <FieldLabel htmlFor="firm-name">Name</FieldLabel>
        <Input
          id="firm-name"
          {...name}
          onChange={(e) => {
            void name.onChange(e);
            onNameChange?.(e.target.value);
          }}
        />
        <FieldError errors={[errors.name]} />
      </Field>
      <Field className="max-w-md" data-invalid={!!errors.timezone}>
        <FieldLabel htmlFor="firm-tz">Timezone</FieldLabel>
        <Input id="firm-tz" list="lucia-timezones" autoComplete="off" {...register("timezone")} />
        <datalist id="lucia-timezones">
          {ZONES.map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
        <FieldError errors={[errors.timezone]} />
      </Field>
      <Field>
        <FieldLabel>Colour</FieldLabel>
        <Controller
          control={control}
          name="color"
          render={({ field }) => (
            <div role="radiogroup" aria-label="Colour" className="flex gap-2">
              {FIRM_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={field.value === c}
                  aria-label={c}
                  onClick={() => field.onChange(c)}
                  style={{ background: c }}
                  className="ring-offset-background size-7 rounded-md ring-offset-2 aria-checked:ring-2 aria-checked:ring-current"
                />
              ))}
            </div>
          )}
        />
      </Field>
    </>
  );
}
