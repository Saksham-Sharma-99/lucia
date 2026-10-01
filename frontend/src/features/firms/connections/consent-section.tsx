import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";

import { createConsentLinkMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectionOut } from "@/api/generated/types.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CopyField } from "@/components/shared/copy-field";
import { Button } from "@/components/ui/button";
import { dateTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

/**
 * The consent link an admin approves to connect Gmail or Slack. Making a new link stops the old
 * one working, so it asks first. The link is shown only to whoever generated it.
 */
export function ConsentSection({
  connection: c,
  admin,
  configured,
}: {
  connection: ConnectionOut;
  /** Who approves the link, e.g. "Google Workspace admin". */
  admin: string;
  configured: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const link = useApiMutation(
    { ...createConsentLinkMutation(), onSuccess: (r) => setUrl(r.url) },
    { stale: STALE.connection, error: "Couldn't create the link" },
  );
  const generate = () => link.mutate({ path: { conn_id: c.id } });

  if (c.status === "connected")
    return (
      <p className="text-sm">
        <span className="text-success">Connected</span> as{" "}
        <span className="font-medium">{c.label}</span>
        {c.connected_at && (
          <span className="text-muted-foreground"> · {dateTime(c.connected_at)}</span>
        )}
      </p>
    );
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Consent link</p>
      <p className="text-muted-foreground text-sm">
        Send this link to the firm's {admin}. When they approve, this connection turns connected on
        its own.
      </p>
      {!configured ? (
        <p className="text-brass text-sm">
          The platform app isn't set up yet, so no link can be made.
        </p>
      ) : url ? (
        <div className="flex items-center gap-2">
          <CopyField value={url} className="flex-1" />
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            <RefreshCwIcon /> New link
          </Button>
        </div>
      ) : (
        <>
          <Button
            variant="outline"
            disabled={link.isPending}
            onClick={() => (c.has_consent_link ? setConfirming(true) : generate())}
          >
            {c.has_consent_link ? "Make a new link" : "Generate link"}
          </Button>
          {c.has_consent_link && (
            <p className="text-muted-foreground text-xs">
              A link was already sent. Making a new one stops the old one working.
            </p>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Make a new link?"
        description="The previous link stops working. Anyone who hasn't approved yet needs the new one."
        confirmLabel="Make a new link"
        onConfirm={generate}
      />
    </div>
  );
}
