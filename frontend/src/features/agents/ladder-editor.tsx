import { ArrowDownIcon, ArrowUpIcon, PlusIcon, TrashIcon } from "lucide-react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { NumberInput, SimpleSelect, type Option } from "@/components/shared/controls";
import { Button } from "@/components/ui/button";
import { hours } from "@/lib/format";

import type { ConfigForm, RungForm } from "./config";

type Values = { config: ConfigForm };
const URGENCY: Option[] = ["P0", "P1", "P2"].map((u) => ({ value: u, label: u }));
const STEP_KINDS: Option[] = [
  { value: "escalate", label: "Escalate to a person" },
  { value: "flag", label: "Flag for review" },
];

/**
 * Follow-up steps, run in order. A step either contacts on a channel or escalates/flags.
 * Only channels whose send tool is enabled in capabilities can be picked.
 */
export function LadderEditor({ channels, disabled }: { channels: Option[]; disabled?: boolean }) {
  const { control, formState, setValue } = useFormContext<Values>();
  const { fields, append, remove, move } = useFieldArray({
    control,
    name: "config.follow_up.ladder",
  });
  const rungs = useWatch({ control, name: "config.follow_up.ladder" });
  const errors = formState.errors.config?.follow_up?.ladder;
  const kindOptions: Option[] = [...channels, ...STEP_KINDS];

  // setValue, not useFieldArray.update: update() remounts the row, losing focus mid-typing.
  const setRung = (i: number, patch: Partial<RungForm>) =>
    setValue(`config.follow_up.ladder.${i}`, { ...rungs[i], ...patch }, { shouldDirty: true });

  return (
    <div className="space-y-2">
      {fields.length === 0 && (
        <p className="text-muted-foreground text-sm">No steps yet. Add the first contact.</p>
      )}
      <ol className="space-y-2">
        {fields.map((field, i) => {
          const r = rungs[i] ?? field;
          const choice = r.kind === "channel" ? (r.channel ?? "") : (r.action ?? "");
          const error =
            errors?.[i]?.channel?.message ?? errors?.[i]?.kind?.message ?? errors?.[i]?.message;
          return (
            <li key={field.id} className="rounded-lg border px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground w-5 text-sm tabular-nums">{i + 1}</span>
                <SimpleSelect
                  label={`Step ${i + 1}`}
                  className="w-52"
                  value={choice || null}
                  placeholder="Pick a step"
                  options={kindOptions}
                  disabled={disabled}
                  invalid={!!error}
                  onChange={(v) =>
                    setRung(
                      i,
                      STEP_KINDS.some((k) => k.value === v)
                        ? {
                            kind: "action",
                            action: v as RungForm["action"],
                            channel: null,
                            urgency: r.urgency ?? "P1",
                          }
                        : { kind: "channel", channel: v, action: null },
                    )
                  }
                />
                <span className="text-muted-foreground text-sm">after</span>
                <NumberInput
                  aria-label="Wait in hours"
                  className="w-20"
                  step="any"
                  inputMode="decimal"
                  value={r.wait_hours}
                  disabled={disabled}
                  onChange={(v) => setRung(i, { wait_hours: v })}
                />
                <span className="text-muted-foreground w-14 text-sm">
                  h · {hours(r.wait_hours)}
                </span>
                {r.kind === "channel" ? (
                  <>
                    <NumberInput
                      aria-label="Attempts"
                      className="w-16"
                      min={1}
                      value={r.attempts}
                      disabled={disabled}
                      onChange={(v) => setRung(i, { attempts: v })}
                    />
                    <span className="text-muted-foreground text-sm">tries</span>
                  </>
                ) : (
                  <SimpleSelect
                    label={`Step ${i + 1} urgency`}
                    className="w-20 min-w-20"
                    value={r.urgency}
                    options={URGENCY}
                    disabled={disabled}
                    onChange={(v) => setRung(i, { urgency: v as RungForm["urgency"] })}
                  />
                )}
                {!disabled && (
                  <span className="ml-auto flex">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Move up"
                      disabled={i === 0}
                      onClick={() => move(i, i - 1)}
                    >
                      <ArrowUpIcon />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Move down"
                      disabled={i === fields.length - 1}
                      onClick={() => move(i, i + 1)}
                    >
                      <ArrowDownIcon />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove step"
                      onClick={() => remove(i)}
                    >
                      <TrashIcon />
                    </Button>
                  </span>
                )}
              </div>
              {error && <p className="text-destructive mt-1.5 pl-7 text-xs">{error}</p>}
            </li>
          );
        })}
      </ol>
      {!disabled && (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            append({
              kind: "channel",
              channel: channels[0]?.value ?? null,
              action: null,
              wait_hours: fields.length ? 72 : 0,
              attempts: 1,
              urgency: null,
            })
          }
        >
          <PlusIcon /> Add step
        </Button>
      )}
      {channels.length === 0 && (
        <p className="text-muted-foreground text-sm">
          Enable a send tool (email, call or Slack message) in Capabilities to add contact steps.
        </p>
      )}
    </div>
  );
}
