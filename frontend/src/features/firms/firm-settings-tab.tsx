import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, get, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { updateFirmMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { FirmDetail, FirmSettings } from "@/api/generated/types.gen";
import { CheckboxGroup } from "@/components/shared/controls";
import { FormSection } from "@/components/shared/form-section";
import { PolicyRuleForm } from "@/components/shared/policy-rule-form";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ALERT_CHANNELS, useRegistry } from "@/features/registry/use-registry";
import { STALE } from "@/lib/invalidate";
import { applyFieldErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { DAYS, type SettingsForm, settingsSchema } from "./model";

function toForm(s: FirmSettings): SettingsForm {
  return {
    business_hours: Object.fromEntries(DAYS.map(([d]) => [d, s.business_hours?.[d] ?? null])),
    quiet_hours: s.quiet_hours ?? null,
    alert_routing: {
      P0: s.alert_routing?.P0 ?? [],
      P1: s.alert_routing?.P1 ?? [],
      P2: s.alert_routing?.P2 ?? [],
    },
    policy_floor: (s.policy_floor ?? []).map((r) => ({ rule: r.rule, params: r.params ?? {} })),
  };
}

export function FirmSettingsTab({ firm }: { firm: FirmDetail }) {
  const registry = useRegistry();
  const form = useForm<SettingsForm>({
    resolver: zodResolver(settingsSchema),
    values: toForm(firm.settings),
  });
  const quiet = useWatch({ control: form.control, name: "quiet_hours" });
  const hours = useWatch({ control: form.control, name: "business_hours" });
  const errorFor = (name: string): string | undefined => get(form.formState.errors, name)?.message;
  const save = useApiMutation(
    {
      ...updateFirmMutation(),
      // Server paths are /settings/...; the form's fields are the settings themselves.
      onError: (e) =>
        applyFieldErrors(form.setError, e, undefined, "settings.").forEach((m) => toast.error(m)),
    },
    { stale: STALE.firm, success: "Settings saved", error: false },
  );
  const submit = form.handleSubmit((settings) =>
    save.mutate({ path: { firm_id: firm.id }, body: { settings } }),
  );

  return (
    <form onSubmit={submit}>
      <FormSection
        title="Business hours"
        description="When agents may contact people for this firm, in the firm's timezone."
      >
        <div className="divide-border divide-y rounded-lg border">
          {DAYS.map(([d, label]) => (
            <div key={d} className="flex flex-wrap items-center gap-3 px-4 py-2">
              <span className="w-24 text-sm">{label}</span>
              <Switch
                aria-label={`${label} open`}
                checked={!!hours[d]}
                onCheckedChange={(on) =>
                  form.setValue(
                    `business_hours.${d}`,
                    on ? { start: "09:00", end: "18:00" } : null,
                    { shouldDirty: true },
                  )
                }
              />
              {hours[d] ? (
                <>
                  <Input
                    type="time"
                    aria-label={`${label} opens`}
                    className="w-36"
                    {...form.register(`business_hours.${d}.start`)}
                  />
                  <span className="text-muted-foreground text-sm">to</span>
                  <Input
                    type="time"
                    aria-label={`${label} closes`}
                    className="w-36"
                    {...form.register(`business_hours.${d}.end`)}
                  />
                  {errorFor(`business_hours.${d}.end`) && (
                    <span className="text-destructive text-xs">
                      {errorFor(`business_hours.${d}.end`)}
                    </span>
                  )}
                </>
              ) : (
                <span className="text-muted-foreground text-sm">Closed</span>
              )}
            </div>
          ))}
        </div>
      </FormSection>
      <FormSection
        title="Quiet hours"
        description="No contact at all inside this window, even if an agent's own rules allow it."
      >
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Switch
            aria-label="Use quiet hours"
            checked={!!quiet}
            onCheckedChange={(on) =>
              form.setValue("quiet_hours", on ? { start: "20:00", end: "08:00" } : null, {
                shouldDirty: true,
              })
            }
          />
          {quiet ? (
            <>
              From
              <Input
                type="time"
                aria-label="Quiet from"
                className="w-36"
                {...form.register("quiet_hours.start")}
              />
              to
              <Input
                type="time"
                aria-label="Quiet until"
                className="w-36"
                {...form.register("quiet_hours.end")}
              />
              {errorFor("quiet_hours.end") && (
                <span className="text-destructive text-xs">{errorFor("quiet_hours.end")}</span>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">Off</span>
          )}
        </div>
      </FormSection>
      <FormSection
        title="Alert routing"
        description="Where alerts go by default, by urgency. Agents can narrow this per mapping."
      >
        <div className="divide-border divide-y rounded-lg border">
          {(["P0", "P1", "P2"] as const).map((u) => (
            <div key={u} className="flex flex-wrap items-center gap-4 px-4 py-2.5">
              <span className="w-10 text-sm font-medium">{u}</span>
              <Controller
                control={form.control}
                name={`alert_routing.${u}`}
                render={({ field }) => (
                  <CheckboxGroup
                    value={field.value}
                    onChange={field.onChange}
                    options={ALERT_CHANNELS}
                  />
                )}
              />
            </div>
          ))}
        </div>
      </FormSection>
      <FormSection
        title="Policy floor"
        description="Rules every agent at this firm must follow, on top of its own. Mappings can only make them stricter."
      >
        <QueryState query={registry} what="The registry">
          {(reg) => (
            <Controller
              control={form.control}
              name="policy_floor"
              render={({ field }) => (
                <PolicyRuleForm
                  rules={reg.rules}
                  value={field.value}
                  onChange={(v) =>
                    field.onChange(v.map((r) => ({ rule: r.rule, params: r.params ?? {} })))
                  }
                  errorFor={(path) => errorFor(`policy_floor.${path}`)}
                />
              )}
            />
          )}
        </QueryState>
      </FormSection>
      <div className="border-border flex justify-end border-t pt-4">
        <Button type="submit" disabled={!form.formState.isDirty || save.isPending}>
          Save settings
        </Button>
      </div>
    </form>
  );
}
