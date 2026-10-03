import { InfoIcon, PlusIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Controller, get, useFormContext, useWatch, type FieldPathByValue } from "react-hook-form";

import {
  CheckboxGroup,
  NumberInput,
  RadioOptions,
  SimpleSelect,
  TagInput,
} from "@/components/shared/controls";
import { FormSection } from "@/components/shared/form-section";
import { PolicyRuleForm } from "@/components/shared/policy-rule-form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ALERT_CHANNELS, type Registry } from "@/features/registry/use-registry";
import { hours } from "@/lib/format";

import { selectedTools, type ConfigForm } from "./config";
import { LadderEditor } from "./ladder-editor";
import { ToolPicker } from "./tool-picker";

export type AgentForm = {
  handle: string;
  name: string;
  description: string;
  use_cases: string[];
  config: ConfigForm;
  changelog: string;
};

type SectionProps = { registry: Registry; disabled?: boolean };
/** `assist` sits above the prompt box (the AI wand in the editors). */
type PromptSectionProps = SectionProps & { assist?: ReactNode };
const URGENCIES = ["P0", "P1", "P2"] as const;
const URGENCY_HINT = { P0: "urgent", P1: "today", P2: "can wait" };

function useError(name: string): string | undefined {
  const { formState } = useFormContext<AgentForm>();
  return get(formState.errors, name)?.message;
}

export function BasicSection({
  disabled,
  handleLocked,
}: {
  disabled?: boolean;
  handleLocked?: boolean;
}) {
  const { register, control } = useFormContext<AgentForm>();
  const handleError = useError("handle");
  const nameError = useError("name");
  return (
    <>
      <FormSection
        title="Identity"
        description="The handle is how people call this agent, e.g. @records. It can't change later."
      >
        <Field data-invalid={!!handleError}>
          <FieldLabel htmlFor="handle">Handle</FieldLabel>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground font-mono">@</span>
            <Input
              id="handle"
              className="font-mono"
              disabled={disabled || handleLocked}
              {...register("handle")}
            />
          </div>
          <FieldDescription>
            3–32 characters: lowercase letters, digits, - or _. Starts with a letter.
          </FieldDescription>
          <FieldError errors={[{ message: handleError }]} />
        </Field>
        <Field data-invalid={!!nameError}>
          <FieldLabel htmlFor="name">Name</FieldLabel>
          <Input id="name" disabled={disabled} {...register("name")} />
          <FieldError errors={[{ message: nameError }]} />
        </Field>
        <Field>
          <FieldLabel htmlFor="description">Description</FieldLabel>
          <Textarea id="description" rows={2} disabled={disabled} {...register("description")} />
        </Field>
      </FormSection>
      <FormSection
        title="Example prompts"
        description="Sentences someone would say to start this agent. The orchestrator uses them to route requests."
      >
        <Controller
          control={control}
          name="use_cases"
          render={({ field }) => (
            <TagInput
              value={field.value}
              onChange={field.onChange}
              disabled={disabled}
              placeholder="e.g. get medical records from Dr. Lee"
            />
          )}
        />
      </FormSection>
    </>
  );
}

export function CapabilitiesSection({ registry, disabled }: SectionProps) {
  const { control } = useFormContext<AgentForm>();
  const error = useError("config.capabilities");
  return (
    <FormSection
      title="Capabilities"
      description="Which apps this agent can use, and which of their tools."
    >
      <Controller
        control={control}
        name="config.capabilities"
        render={({ field }) => (
          <ToolPicker
            connectors={registry.connectors}
            value={field.value}
            onChange={field.onChange}
            readOnly={disabled}
          />
        )}
      />
      {error && <p className="text-destructive text-sm">{error}</p>}
    </FormSection>
  );
}

export function PromptSection({ registry, disabled, assist }: PromptSectionProps) {
  const { register, control } = useFormContext<AgentForm>();
  const prompt = useWatch({ control, name: "config.system_prompt" }) ?? "";
  const promptError = useError("config.system_prompt");
  const models = registry.models.map((m) => ({ value: m, label: m }));
  return (
    <>
      <FormSection
        title="System prompt"
        description="The agent's standing instructions. Plain language works best."
      >
        {assist}
        <Field data-invalid={!!promptError}>
          <Textarea
            aria-label="System prompt"
            className="min-h-48 font-mono text-[0.8125rem] leading-relaxed"
            disabled={disabled}
            {...register("config.system_prompt")}
          />
          <FieldDescription className="text-right tabular-nums">
            {prompt.length.toLocaleString()} / 20,000
          </FieldDescription>
          <FieldError errors={[{ message: promptError }]} />
        </Field>
      </FormSection>
      <FormSection
        title="Models"
        description="Loop runs the agent, guardrail checks each send, judge grades outcomes."
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {(["loop", "guardrail", "judge"] as const).map((role) => (
            <ModelField key={role} role={role} options={models} disabled={disabled} />
          ))}
        </div>
      </FormSection>
    </>
  );
}

const MODEL_ROLES = {
  loop: {
    label: "Loop",
    help: "Runs the agent: reads what has happened, decides the next step and writes each message. It does the real work, so use your most capable model.",
  },
  guardrail: {
    label: "Guardrail",
    help: "Checks every outgoing email, call or message against the policy rules just before it is sent, and blocks it if a rule fails. It runs on each send, so a fast, cheaper model fits.",
  },
  judge: {
    label: "Judge",
    help: "Grades how runs went (for evals and quality reviews). It never acts or contacts anyone; it only scores the work afterwards.",
  },
} as const;

function ModelField({
  role,
  options,
  disabled,
}: {
  role: "loop" | "guardrail" | "judge";
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  const { control } = useFormContext<AgentForm>();
  const error = useError(`config.models.${role}`);
  return (
    <Field data-invalid={!!error}>
      <div className="flex items-center gap-1.5">
        <FieldLabel>{MODEL_ROLES[role].label}</FieldLabel>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                aria-label={`What the ${role} model does`}
                className="text-muted-foreground hover:text-foreground"
              >
                <InfoIcon className="size-3.5" />
              </button>
            }
          />
          <TooltipContent className="max-w-64">{MODEL_ROLES[role].help}</TooltipContent>
        </Tooltip>
      </div>
      <Controller
        control={control}
        name={`config.models.${role}`}
        render={({ field }) => (
          <SimpleSelect
            label={MODEL_ROLES[role].label}
            value={field.value}
            onChange={field.onChange}
            options={options}
            disabled={disabled}
            invalid={!!error}
          />
        )}
      />
      <FieldError errors={[{ message: error }]} />
    </Field>
  );
}

export function PoliciesSection({ registry, disabled }: SectionProps) {
  const { control, setValue, formState } = useFormContext<AgentForm>();
  const capabilities = useWatch({ control, name: "config.capabilities" });
  const pack = useWatch({ control, name: "config.policy_pack" });
  const mode = useWatch({ control, name: "config.alert_policy.urgency_mode" });
  const selected = selectedTools({ capabilities });
  const external = registry.tools.some(
    (t) => selected.has(t.name) && t.risk_tier === "external_comm",
  );
  const missingMinPack = external && !pack.some((p) => p.rule === "recipient_must_be_contact");
  const packError = useError("config.policy_pack");

  return (
    <>
      <FormSection
        title="Policy rules"
        description="Checked before every message or call. A blocked send is turned into a question for a person."
      >
        {missingMinPack && !disabled && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              This agent contacts people outside the firm, so it must only contact people on the
              matter.
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setValue(
                    "config.policy_pack",
                    [{ rule: "recipient_must_be_contact", params: {} }, ...pack],
                    { shouldDirty: true },
                  )
                }
              >
                <PlusIcon /> Add the rule
              </Button>
            </AlertDescription>
          </Alert>
        )}
        <Controller
          control={control}
          name="config.policy_pack"
          render={({ field }) => (
            <PolicyRuleForm
              rules={registry.rules}
              value={field.value}
              onChange={(v) =>
                field.onChange(v.map((r) => ({ rule: r.rule, params: r.params ?? {} })))
              }
              disabled={disabled}
              errorFor={(path) => get(formState.errors, `config.policy_pack.${path}`)?.message}
            />
          )}
        />
        {packError && <p className="text-destructive text-sm">{packError}</p>}
      </FormSection>
      <FormSection
        title="When to ask a person"
        description="Situations where the agent stops and asks instead of acting."
      >
        <Controller
          control={control}
          name="config.hitl.ask_on"
          render={({ field }) => (
            <TagInput
              value={field.value}
              onChange={field.onChange}
              disabled={disabled}
              placeholder="e.g. fee_required"
            />
          )}
        />
        <Controller
          control={control}
          name="config.hitl.verify_evidence_below"
          render={({ field }) => (
            <Field>
              <FieldLabel>
                Ask to verify evidence below {Math.round(field.value * 100)}% confidence
              </FieldLabel>
              <Slider
                className="max-w-sm"
                min={0}
                max={1}
                step={0.05}
                value={[field.value]}
                disabled={disabled}
                onValueChange={(v) => field.onChange(Array.isArray(v) ? v[0] : v)}
              />
            </Field>
          )}
        />
      </FormSection>
      <FormSection
        title="Alerts"
        description="How urgent findings are, and where each urgency goes by default."
      >
        <Controller
          control={control}
          name="config.alert_policy.urgency_mode"
          render={({ field }) => (
            <RadioOptions
              value={field.value}
              onChange={field.onChange}
              disabled={disabled}
              options={[
                {
                  value: "auto",
                  label: "Decide per finding",
                  hint: "The agent picks P0–P2 from what it found.",
                },
                { value: "fixed", label: "Always the same urgency" },
              ]}
            />
          )}
        />
        {mode === "fixed" && (
          <Controller
            control={control}
            name="config.alert_policy.fixed_urgency"
            render={({ field }) => (
              <SimpleSelect
                label="Fixed urgency"
                className="w-32"
                value={field.value}
                onChange={field.onChange}
                disabled={disabled}
                invalid={!!get(formState.errors, "config.alert_policy.fixed_urgency")}
                options={URGENCIES.map((u) => ({ value: u, label: u }))}
              />
            )}
          />
        )}
        <div className="divide-border divide-y rounded-lg border">
          {URGENCIES.map((u) => (
            <div key={u} className="flex flex-wrap items-center gap-4 px-4 py-2.5">
              <span className="w-24 text-sm font-medium">
                {u} <span className="text-muted-foreground font-normal">{URGENCY_HINT[u]}</span>
              </span>
              <Controller
                control={control}
                name={`config.alert_policy.default_channels.${u}`}
                render={({ field }) => (
                  <CheckboxGroup
                    value={field.value}
                    onChange={field.onChange}
                    options={ALERT_CHANNELS}
                    disabled={disabled}
                  />
                )}
              />
            </div>
          ))}
        </div>
      </FormSection>
    </>
  );
}

export function SchedulesSection({ registry, disabled }: SectionProps) {
  const { control, setValue } = useFormContext<AgentForm>();
  const capabilities = useWatch({ control, name: "config.capabilities" });
  const mode = useWatch({ control, name: "config.follow_up.mode" });
  const recurrence = useWatch({ control, name: "config.recurrence" });
  const selected = selectedTools({ capabilities });
  const channels = registry.channels
    .filter((c) => c.channel_tool && selected.has(c.channel_tool))
    .map((c) => ({ value: c.name, label: c.display_name }));
  const minMaxError = useError("config.follow_up.dynamic.min_hours");
  const channelsError = useError("config.follow_up.dynamic.channels.0");

  return (
    <>
      <FormSection title="Follow-up" description="What the agent does when nobody replies.">
        <Controller
          control={control}
          name="config.follow_up.mode"
          render={({ field }) => (
            <RadioOptions
              value={field.value}
              onChange={field.onChange}
              disabled={disabled}
              options={[
                { value: "none", label: "No follow-up" },
                {
                  value: "fixed_ladder",
                  label: "Fixed steps",
                  hint: "The same sequence every time, e.g. email twice, then call.",
                },
                {
                  value: "dynamic",
                  label: "Agent decides",
                  hint: "The agent picks when and how, within limits.",
                },
              ]}
            />
          )}
        />
        {mode === "fixed_ladder" && <LadderEditor channels={channels} disabled={disabled} />}
        {mode === "dynamic" && (
          <div className="grid gap-4 rounded-lg border p-4">
            <div className="flex flex-wrap items-end gap-4">
              <NumberFieldRow
                name="config.follow_up.dynamic.min_hours"
                label="Wait at least (hours)"
                decimal
                disabled={disabled}
              />
              <NumberFieldRow
                name="config.follow_up.dynamic.max_hours"
                label="Wait at most (hours)"
                decimal
                disabled={disabled}
              />
              <label className="flex items-center gap-2 pb-1.5 text-sm">
                <Controller
                  control={control}
                  name="config.follow_up.dynamic.business_hours"
                  render={({ field }) => (
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={disabled}
                    />
                  )}
                />
                Business hours only
              </label>
            </div>
            {minMaxError && <p className="text-destructive text-sm">{minMaxError}</p>}
            <Field>
              <FieldLabel>Channels</FieldLabel>
              <Controller
                control={control}
                name="config.follow_up.dynamic.channels"
                render={({ field }) => (
                  <CheckboxGroup
                    value={field.value}
                    onChange={field.onChange}
                    options={channels}
                    disabled={disabled}
                  />
                )}
              />
              <FieldError errors={[{ message: channelsError }]} />
            </Field>
            <div className="flex flex-wrap items-end gap-4">
              <NumberFieldRow
                name="config.follow_up.dynamic.escalate_after.attempts"
                label="Escalate after (attempts)"
                min={1}
                disabled={disabled}
              />
              <Field className="w-32">
                <FieldLabel>Urgency</FieldLabel>
                <Controller
                  control={control}
                  name="config.follow_up.dynamic.escalate_after.urgency"
                  render={({ field }) => (
                    <SimpleSelect
                      label="Urgency"
                      value={field.value}
                      onChange={field.onChange}
                      disabled={disabled}
                      options={URGENCIES.map((u) => ({ value: u, label: u }))}
                    />
                  )}
                />
              </Field>
            </div>
          </div>
        )}
      </FormSection>
      <FormSection
        title="Repeats"
        description="For agents that run in cycles, like a check-in every two weeks."
      >
        <div className="flex items-center gap-3 text-sm">
          <Switch
            aria-label="Repeat on a schedule"
            checked={!!recurrence}
            disabled={disabled}
            onCheckedChange={(on) =>
              setValue("config.recurrence", on ? { every_days: 14 } : null, { shouldDirty: true })
            }
          />
          {recurrence ? (
            <>
              Every
              <Controller
                control={control}
                name="config.recurrence.every_days"
                render={({ field }) => (
                  <NumberInput
                    aria-label="Repeat every N days"
                    className="w-20"
                    step="any"
                    inputMode="decimal"
                    value={field.value}
                    onChange={field.onChange}
                    disabled={disabled}
                  />
                )}
              />
              days
              {!Number.isInteger(recurrence.every_days) && recurrence.every_days > 0 && (
                <span className="text-muted-foreground">≈ {hours(recurrence.every_days * 24)}</span>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">Runs once per matter</span>
          )}
        </div>
      </FormSection>
      <FormSection title="Limits" description="When a run stops on its own.">
        <div className="flex flex-wrap items-end gap-4">
          <NumberFieldRow
            name="config.end_conditions.max_duration_days"
            label="Max duration (days)"
            min={1}
            disabled={disabled}
          />
          <NumberFieldRow
            name="config.end_conditions.max_steps"
            label="Max steps"
            min={10}
            disabled={disabled}
          />
          <NumberFieldRow
            name="config.max_turns_per_episode"
            label="Max turns per wake-up"
            min={1}
            disabled={disabled}
          />
          <Field className="w-44">
            <FieldLabel>When the matter closes</FieldLabel>
            <Controller
              control={control}
              name="config.end_conditions.on_subject_closed"
              render={({ field }) => (
                <SimpleSelect
                  label="When the matter closes"
                  value={field.value}
                  onChange={field.onChange}
                  disabled={disabled}
                  options={[
                    { value: "end", label: "End the run" },
                    { value: "pause", label: "Pause the run" },
                  ]}
                />
              )}
            />
          </Field>
        </div>
      </FormSection>
    </>
  );
}

function NumberFieldRow({
  name,
  label,
  min = 0,
  disabled,
  decimal,
}: {
  name: FieldPathByValue<AgentForm, number>;
  label: string;
  min?: number;
  disabled?: boolean;
  /** Accept fractions (0.1 h = 6 min). */
  decimal?: boolean;
}) {
  const { control } = useFormContext<AgentForm>();
  const error = useError(name);
  return (
    <Field className="w-44" data-invalid={!!error}>
      <FieldLabel>{label}</FieldLabel>
      <Controller
        control={control}
        name={name}
        render={({ field }) => (
          <NumberInput
            value={field.value}
            onChange={field.onChange}
            min={min}
            step={decimal ? "any" : undefined}
            inputMode={decimal ? "decimal" : undefined}
            disabled={disabled}
            aria-invalid={!!error}
          />
        )}
      />
      <FieldError errors={[{ message: error }]} />
    </Field>
  );
}
