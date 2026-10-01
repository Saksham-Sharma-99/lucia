import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";

import {
  activateFirmMutation,
  deactivateFirmMutation,
  updateFirmMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { FirmDetail } from "@/api/generated/types.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FormSection } from "@/components/shared/form-section";
import { Button } from "@/components/ui/button";
import { AffectedMappings } from "@/features/mappings/affected-mappings";
import { useActiveMappings } from "@/features/mappings/hooks";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { FirmFields } from "./firm-fields";
import { firmDetailsSchema, type FirmDetails } from "./model";

export function FirmOverviewTab({ firm }: { firm: FirmDetail }) {
  const [confirming, setConfirming] = useState(false);
  const form = useForm<FirmDetails>({
    resolver: zodResolver(firmDetailsSchema),
    values: { name: firm.name, timezone: firm.timezone, color: firm.color },
  });
  const update = useApiMutation(
    {
      ...updateFirmMutation(),
      onError: (e) => showFormErrors(form.setError, e),
    },
    { stale: STALE.firm, success: "Saved", error: false },
  );
  const active = firm.status === "active";
  const connections = Object.values(firm.connection_counts ?? {}).reduce((a, b) => a + b, 0);
  return (
    <>
      <FormProvider {...form}>
        <form
          onSubmit={form.handleSubmit((body) =>
            update.mutate({ path: { firm_id: firm.id }, body }),
          )}
        >
          <FormSection title="Details" description="The slug can't change.">
            <FirmFields />
            {form.formState.errors.root && (
              <p role="alert" className="text-destructive text-sm">
                {form.formState.errors.root.message}
              </p>
            )}
            <Button type="submit" disabled={!form.formState.isDirty || update.isPending}>
              Save changes
            </Button>
          </FormSection>
        </form>
      </FormProvider>
      <FormSection
        title="Status"
        description={
          active
            ? "Deactivating turns off every mapping at this firm. Turning it back on doesn't restore them."
            : "Inactive firms can't run agents."
        }
      >
        <div className="flex items-center gap-4 text-sm">
          <span>
            {connections} connection{connections === 1 ? "" : "s"} ·{" "}
            {firm.mapping_counts.active ?? 0} active mappings
          </span>
          <Button variant={active ? "destructive" : "default"} onClick={() => setConfirming(true)}>
            {active ? "Deactivate firm" : "Activate firm"}
          </Button>
        </div>
      </FormSection>
      {confirming && <StatusDialog firm={firm} onClose={() => setConfirming(false)} />}
    </>
  );
}

/** Deactivating lists the mappings it turns off; activating only confirms. */
function StatusDialog({ firm, onClose }: { firm: FirmDetail; onClose: () => void }) {
  const active = firm.status === "active";
  // Only deactivating turns mappings off, so only then is there anything to look up.
  const affected = useActiveMappings({ firm_id: firm.id }, active);
  const stale = [...STALE.firm, ...STALE.mapping];
  const deactivate = useApiMutation(deactivateFirmMutation(), {
    stale,
    success: `${firm.name} deactivated`,
  });
  const activate = useApiMutation(activateFirmMutation(), {
    stale,
    success: `${firm.name} activated`,
  });
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => open || onClose()}
      title={active ? `Deactivate ${firm.name}?` : `Activate ${firm.name}?`}
      destructive={active}
      confirmLabel={active ? "Deactivate" : "Activate"}
      confirmDisabled={active && affected.isPending}
      onConfirm={() => (active ? deactivate : activate).mutate({ path: { firm_id: firm.id } })}
      description={
        active ? (
          <AffectedMappings
            query={affected}
            intro="These mappings will be turned off:"
            none="No agents are active at this firm."
            name={(m) => `@${m.agent_handle} v${m.version}`}
          />
        ) : (
          "Mappings stay off until you turn them on."
        )
      }
    />
  );
}
