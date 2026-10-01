import { TrashIcon } from "lucide-react";
import { useState } from "react";

import { deleteConnectionMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectionOut, ConnectorOut, PlatformStatus } from "@/api/generated/types.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { relativeTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { SETUP, isConfigured } from "../model";
import { ConsentSection } from "./consent-section";
import { SecretsSection } from "./secrets-section";
import { TestsPanel } from "./tests-panel";

export function ConnectionCard({
  connection: c,
  connector,
  platform,
}: {
  connection: ConnectionOut;
  connector?: ConnectorOut;
  /** Missing while the registry is unavailable; setup then stays hidden. */
  platform?: PlatformStatus;
}) {
  const [deleting, setDeleting] = useState(false);
  const remove = useApiMutation(deleteConnectionMutation(), {
    stale: STALE.connection,
    success: `Removed ${c.label}`,
    error: "Couldn't remove it",
  });
  // Agents whose mappings bind this connection; such a connection can't be removed.
  const usedBy = (c.used_by ?? []).map((h) => `@${h}`);
  const inUse = usedBy.length > 0;
  return (
    <article className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <ConnectorIcon connector={c.connector} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{c.label}</p>
          <p className="text-muted-foreground text-xs">
            {connector?.display_name ?? c.connector}
            {c.connected_at && ` · connected ${relativeTime(c.connected_at)}`}
            {inUse && ` · used by ${usedBy.join(", ")}`}
          </p>
        </div>
        <StatusBadge status={c.status} />
        {c.status === "connected" && <StatusBadge status={c.health} />}
        <Tooltip>
          <TooltipTrigger
            render={
              <span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${c.label}`}
                  disabled={inUse}
                  onClick={() => setDeleting(true)}
                >
                  <TrashIcon />
                </Button>
              </span>
            }
          />
          <TooltipContent>
            {inUse ? `Used by ${usedBy.join(", ")}. Unbind it first.` : "Remove this connection"}
          </TooltipContent>
        </Tooltip>
      </header>
      <div className="space-y-5 px-4 py-4">
        {platform && (c.connector === "gmail" || c.connector === "slack") && (
          <ConsentSection
            connection={c}
            admin={SETUP[c.connector].admin}
            configured={isConfigured(platform, c.connector)}
          />
        )}
        {c.connector === "vapi" && (
          <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">Number</dt>
            <dd className="font-mono">{String(c.config.phone_number ?? "—")}</dd>
            <dt className="text-muted-foreground">Assistant</dt>
            <dd className="font-mono text-xs">{String(c.config.assistant_id ?? "—")}</dd>
          </dl>
        )}
        <SecretsSection connection={c} />
        {c.status === "connected" && connector && (
          <TestsPanel connection={c} tools={connector.tools} />
        )}
      </div>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Remove ${c.label}?`}
        description="Its stored secrets are deleted. Reconnecting needs a new consent link or setup."
        confirmLabel="Remove"
        destructive
        onConfirm={() => remove.mutate({ path: { conn_id: c.id } })}
      />
    </article>
  );
}
