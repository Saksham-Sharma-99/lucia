import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { createConnectionMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectorOut, PlatformStatus } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { SETUP, isConfigured, isSetupConnector, type SetupConnector } from "../model";

const schema = z.object({
  connector: z.enum(["gmail", "slack", "vapi"]),
  label: z.string().max(120),
  numberId: z.string().trim(),
});
type Values = z.infer<typeof schema>;

/** Adds a connection. Gmail/Slack start pending (a consent link comes next); Vapi is checked now. */
export function AddConnectionDialog({
  firmId,
  connectors,
  platform,
  onClose,
}: {
  firmId: string;
  connectors: ConnectorOut[];
  platform: PlatformStatus;
  onClose: () => void;
}) {
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      connector: "gmail",
      label: "",
      numberId: "",
    },
  });
  const connector = useWatch({ control: form.control, name: "connector" });
  const create = useApiMutation(
    {
      ...createConnectionMutation(),
      onSuccess: onClose,
      onError: (e) => showFormErrors(form.setError, e),
    },
    {
      stale: STALE.connection,
      success: (c) =>
        c.status === "connected"
          ? `${c.label} is connected`
          : `${c.label} added. Generate its consent link next.`,
      error: false,
    },
  );
  const choices = connectors.filter((c) => c.available && isSetupConnector(c.name));
  const name = (n: string) => connectors.find((c) => c.name === n)?.display_name ?? n;
  const configured = isConfigured(platform, connector);
  const setup = SETUP[connector];
  const { errors } = form.formState;

  const submit = form.handleSubmit((v) =>
    create.mutate({
      path: { firm_id: firmId },
      body:
        v.connector === "vapi"
          ? {
              connector: "vapi",
              label: v.label || name(v.connector),
              // Empty: the platform's default number (VAPI_PHONE_NUMBER_ID).
              config: v.numberId ? { phone_number_id: v.numberId } : {},
            }
          : { connector: v.connector, label: v.label || name(v.connector) },
    }),
  );

  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Add a connection</DialogTitle>
          </DialogHeader>
          <div className="mt-2 space-y-4">
            <div role="radiogroup" aria-label="Connector" className="grid grid-cols-3 gap-2">
              {choices.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  role="radio"
                  aria-checked={connector === c.name}
                  onClick={() => form.setValue("connector", c.name as SetupConnector)}
                  className="aria-checked:border-brass flex flex-col items-start gap-2 rounded-lg border p-3 text-left text-sm"
                >
                  <ConnectorIcon connector={c.name} />
                  {c.display_name}
                </button>
              ))}
            </div>
            {!configured && (
              <p className="text-brass text-sm">
                The platform's {name(connector)} app isn't set up yet (backend .env), so this
                connection can't be completed.
              </p>
            )}
            <Field>
              <FieldLabel htmlFor="conn-label">Label</FieldLabel>
              <Input
                id="conn-label"
                placeholder={setup.labelPlaceholder}
                {...form.register("label")}
              />
              <FieldDescription>{setup.labelHint}</FieldDescription>
            </Field>
            {connector === "vapi" && (
              <Field data-invalid={!!errors.numberId}>
                <FieldLabel htmlFor="conn-number-id">Vapi phone number id</FieldLabel>
                <Input
                  id="conn-number-id"
                  className="font-mono"
                  autoComplete="off"
                  {...form.register("numberId")}
                />
                <FieldDescription>
                  Leave empty to use the platform's default number. Otherwise copy the id from Vapi
                  → Phone Numbers after importing the number there (Twilio, Telnyx or Vonage);
                  Vapi's free numbers can't place calls.
                </FieldDescription>
                <FieldError errors={[errors.numberId]} />
              </Field>
            )}
            {errors.root && (
              <p role="alert" className="text-destructive text-sm">
                {errors.root.message}
              </p>
            )}
          </div>
          <DialogFooter className="mt-4">
            <Button type="submit" disabled={create.isPending || !configured}>
              {create.isPending
                ? "Adding…"
                : connector === "vapi"
                  ? "Add the number"
                  : "Add connection"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
