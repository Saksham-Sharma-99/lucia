import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PlusIcon } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";
import { toast } from "sonner";

import { listConnectionsOptions } from "@/api/generated/@tanstack/react-query.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useRegistry } from "@/features/registry/use-registry";
import { STALE, invalidate } from "@/lib/invalidate";

import { AddConnectionDialog } from "./add-connection-dialog";
import { ConnectionCard } from "./connection-card";

/** Polls while a consent link is out, so an admin's approval shows up without a reload. */
const POLL_MS = 5000;

export function ConnectionsTab({
  firmId,
  connected,
  onConnectedSeen,
}: {
  firmId: string;
  connected?: string;
  onConnectedSeen: () => void;
}) {
  const registry = useRegistry();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const connections = useQuery({
    ...listConnectionsOptions({ path: { firm_id: firmId } }),
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "pending") ? POLL_MS : false),
  });

  // Back from an approved consent link (?connected=<id>): say so once, then drop the param.
  const announce = useEffectEvent(() => {
    void invalidate(queryClient, ...STALE.connection);
    toast.success("Connected. You can run tests now.");
    onConnectedSeen();
  });
  useEffect(() => {
    if (connected) announce();
  }, [connected]);

  const reg = registry.data;
  const add = (
    <Button disabled={!reg} onClick={() => setAdding(true)}>
      <PlusIcon /> Add connection
    </Button>
  );
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-muted-foreground text-sm">
          Each connection is this firm's own mailbox, Slack workspace or phone number. Secrets are
          stored encrypted and never shown.
        </p>
        {add}
      </div>
      {registry.isError && (
        // The list still works without the registry; only setup and tests need it.
        <p role="status" className="text-brass text-sm">
          The registry didn't load, so adding, setup and tests are unavailable.{" "}
          <button className="underline" onClick={() => void registry.refetch()}>
            Try again
          </button>
        </p>
      )}
      <QueryState
        query={connections}
        what="Connections"
        loading={<Skeleton className="h-40 w-full" />}
        isEmpty={(list) => list.length === 0}
        empty={
          <EmptyState
            title="No connections yet"
            description="Connect Gmail, Slack or a phone number so agents can act for this firm."
            action={add}
          />
        }
      >
        {(list) =>
          list.map((c) => (
            <ConnectionCard
              key={c.id}
              connection={c}
              connector={reg?.connectors.find((x) => x.name === c.connector)}
              platform={reg?.platform}
            />
          ))
        }
      </QueryState>
      {adding && reg && (
        <AddConnectionDialog
          firmId={firmId}
          connectors={reg.connectors}
          platform={reg.platform}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  );
}
