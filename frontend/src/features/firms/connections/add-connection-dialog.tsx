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
import { Switch } from "@/components/ui/switch";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { SETUP, isConfigured, isSetupConnector, type SetupConnector } from "../model";

const schema = z
  .object({
    connector: z.enum(["gmail", "slack", "vapi"]),
    label: z.string().max(120),
    phone: z.string(),
    ownTwilio: z.boolean(),
    sid: z.string(),
    token: z.string(),
  })
  .superRefine((v, ctx) => {
    if (v.connector !== "vapi") return;
    if (!/^\+[1-9]\d{6,14}$/.test(v.phone))
      ctx.addIssue({
        code: "custom",
        path: ["phone"],
        message: "Use international format, e.g. +14155550123",
      });
    if (v.ownTwilio && !v.sid)
      ctx.addIssue({ code: "custom", path: ["sid"], message: "Enter the account SID" });
    if (v.ownTwilio && !v.token)
      ctx.addIssue({ code: "custom", path: ["token"], message: "Enter the auth token" });
  });
type Values = z.infer<typeof schema>;

/** Adds a connection. Gmail/Slack start pending (a consent link comes next); Vapi is set up now. */
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
      phone: "",
      ownTwilio: false,
      sid: "",
      token: "",
    },
  });
  const [connector, ownTwilio] = useWatch({
    control: form.control,
    name: ["connector", "ownTwilio"],
  });
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
              label: v.label || v.phone,
              config: { phone_number: v.phone },
              secrets: v.ownTwilio ? { twilio_account_sid: v.sid, twilio_auth_token: v.token } : {},
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
              <>
                <Field data-invalid={!!errors.phone}>
                  <FieldLabel htmlFor="conn-phone">Phone number</FieldLabel>
                  <Input
                    id="conn-phone"
                    className="font-mono"
                    placeholder="+14155550123"
                    {...form.register("phone")}
                  />
                  <FieldDescription>
                    A Twilio number. Lucia creates the voice assistant for it.
                  </FieldDescription>
                  <FieldError errors={[errors.phone]} />
                </Field>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={ownTwilio}
                    onCheckedChange={(on) => form.setValue("ownTwilio", on)}
                  />
                  Use the firm's own Twilio account
                </label>
                {ownTwilio && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field data-invalid={!!errors.sid}>
                      <FieldLabel htmlFor="tw-sid">Account SID</FieldLabel>
                      <Input id="tw-sid" autoComplete="off" {...form.register("sid")} />
                      <FieldError errors={[errors.sid]} />
                    </Field>
                    <Field data-invalid={!!errors.token}>
                      <FieldLabel htmlFor="tw-token">Auth token</FieldLabel>
                      <Input
                        id="tw-token"
                        type="password"
                        autoComplete="off"
                        {...form.register("token")}
                      />
                      <FieldError errors={[errors.token]} />
                    </Field>
                  </div>
                )}
              </>
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
                  ? "Add and set up the number"
                  : "Add connection"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
