import { XIcon } from "lucide-react";
import { useState, type ComponentProps } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type Option = { value: string; label: string };

/** A single-choice select over plain `{value, label}` options. */
export function SimpleSelect({
  value,
  onChange,
  options,
  placeholder = "Select…",
  disabled,
  className,
  id,
  invalid,
  label,
}: {
  value: string | null | undefined;
  onChange: (value: string) => void;
  options: readonly Option[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  invalid?: boolean;
  /** The accessible name; keep it equal to a visible label when there is one. */
  label: string;
}) {
  return (
    <Select
      value={value ?? null}
      onValueChange={(v) => v !== null && onChange(v as string)}
      items={options}
      disabled={disabled}
    >
      <SelectTrigger
        id={id}
        aria-label={label}
        className={cn("w-full min-w-40", className)}
        aria-invalid={invalid}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Checkboxes for a multi-choice list; keeps the option order in the value. */
export function CheckboxGroup<V extends string>({
  value,
  onChange,
  options,
  disabled,
  className,
  label,
}: {
  value: readonly V[];
  onChange: (value: V[]) => void;
  options: readonly { value: V; label: string }[];
  disabled?: boolean;
  className?: string;
  /** Names the group for screen readers. */
  label?: string;
}) {
  const toggle = (v: V, on: boolean) =>
    onChange(options.map((o) => o.value).filter((o) => (o === v ? on : value.includes(o))));
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("flex flex-wrap gap-x-5 gap-y-2", className)}
    >
      {options.map((o) => (
        <label key={o.value} className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={value.includes(o.value)}
            onCheckedChange={(on) => toggle(o.value, on === true)}
            disabled={disabled}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/** Free-text list entries (example prompts, HITL triggers). Enter adds, × removes. */
export function TagInput({
  value,
  onChange,
  placeholder,
  max = 20,
  disabled,
}: {
  value: readonly string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  max?: number;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !value.includes(v) && value.length < max) onChange([...value, v]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {value.map((v) => (
            <li
              key={v}
              className="bg-secondary flex items-center gap-1 rounded-md py-0.5 pr-1 pl-2 text-sm"
            >
              {v}
              {!disabled && (
                <button
                  type="button"
                  aria-label={`Remove ${v}`}
                  className="text-muted-foreground hover:text-foreground rounded p-0.5"
                  onClick={() => onChange(value.filter((x) => x !== v))}
                >
                  <XIcon className="size-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!disabled && value.length < max && (
        <Input
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={add}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
      )}
    </div>
  );
}

/**
 * A number input that reports numbers. While a value is being edited (e.g. cleared to retype)
 * the text is kept as typed. On blur, an emptied field shows the last valid number again and a
 * number below `min` is raised to `min`.
 */
export function NumberInput({
  value,
  onChange,
  min = 0,
  onBlur,
  ...props
}: Omit<ComponentProps<typeof Input>, "value" | "onChange" | "type"> & {
  value: number | undefined;
  onChange: (value: number) => void;
  min?: number;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <Input
      type="number"
      inputMode="numeric"
      min={min}
      value={draft ?? (Number.isFinite(value) ? String(value) : "")}
      onChange={(e) => {
        setDraft(e.target.value);
        if (e.target.value !== "" && Number.isFinite(Number(e.target.value)))
          onChange(Number(e.target.value));
      }}
      onBlur={(e) => {
        // Typing may pass through values below min ("6" on the way to "60"); settle on leaving.
        if (draft && Number(draft) < min) onChange(min);
        setDraft(null);
        onBlur?.(e);
      }}
      {...props}
    />
  );
}

/** Radio buttons over `{value, label}` options, each with an optional hint line. */
export function RadioOptions({
  value,
  onChange,
  options,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: readonly (Option & { hint?: string })[];
  disabled?: boolean;
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(v) => onChange(v as string)}
      disabled={disabled}
      className="gap-3"
    >
      {options.map((o) => (
        <label key={o.value} className="flex items-start gap-2.5 text-sm">
          <RadioGroupItem value={o.value} className="mt-0.5" />
          <span>
            {o.label}
            {o.hint && <span className="text-muted-foreground block">{o.hint}</span>}
          </span>
        </label>
      ))}
    </RadioGroup>
  );
}
