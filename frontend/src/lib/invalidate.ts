import type { QueryClient } from "@tanstack/react-query";

import type * as sdk from "@/api/generated/sdk.gen";

/** A generated operation name, e.g. "listAgents". Typos fail type-checking. */
export type Operation = keyof typeof sdk;

/**
 * Generated query keys look like `[{ _id: "listAgents", path, query }]`. Invalidate every
 * cached query of the given operations, whatever their params.
 */
export function invalidate(queryClient: QueryClient, ...operations: readonly Operation[]) {
  return queryClient.invalidateQueries({
    predicate: (q) => {
      const head = q.queryKey[0] as { _id?: string } | undefined;
      return !!head?._id && (operations as readonly string[]).includes(head._id);
    },
  });
}

/** What each kind of change makes stale. */
export const STALE = {
  agent: ["listAgents", "getAgent", "listAgentVersions", "getAgentVersion", "diffAgentVersions"],
  // Mapping changes move counts shown on agents and firms, and each connection's used_by.
  mapping: [
    "listMappings",
    "listConnections",
    "getMapping",
    "getMappingChecklist",
    "getAgent",
    "listAgents",
    "getFirm",
    "listFirms",
  ],
  firm: ["listFirms", "getFirm"],
  connection: ["listConnections", "getConnection", "getMappingChecklist", "getFirm", "listFirms"],
} as const satisfies Record<string, readonly Operation[]>;
