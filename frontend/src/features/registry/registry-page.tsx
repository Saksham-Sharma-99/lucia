import { PageHeader } from "@/components/shared/page-header";
import { QueryState } from "@/components/shared/query-state";
import { Skeleton } from "@/components/ui/skeleton";

import { ConnectorCatalog } from "./connector-catalog";
import { useRegistry } from "./use-registry";

export function RegistryPage({
  connector,
  onConnector,
}: {
  connector?: string;
  onConnector: (name: string | undefined) => void;
}) {
  const registry = useRegistry();
  return (
    <>
      <PageHeader
        title="Registry"
        description="The apps agents can act in. Defined in code; read-only here."
      />
      <QueryState
        query={registry}
        what="The registry"
        loading={<Skeleton className="h-64 w-full" />}
      >
        {(reg) => <ConnectorCatalog registry={reg} open={connector} onOpen={onConnector} />}
      </QueryState>
    </>
  );
}
