import { useQuery } from "@tanstack/react-query";

import {
  getMappingChecklistOptions,
  listMappingsOptions,
} from "@/api/generated/@tanstack/react-query.gen";

/** The active mappings a destructive action would turn off (first 20, plus the total). */
export const useActiveMappings = (
  filter: { firm_id: string } | { agent_id: string },
  enabled = true,
) =>
  useQuery({
    ...listMappingsOptions({ query: { ...filter, status: "active", limit: 20 } }),
    enabled,
  });

export function useChecklist(
  firmId: string,
  versionId: string | undefined,
  identities: Record<string, string>,
) {
  return useQuery({
    ...getMappingChecklistOptions({
      query: {
        firm_id: firmId,
        agent_prompt_id: versionId ?? "",
        identities: Object.entries(identities).map(([k, v]) => `${k}:${v}`),
      },
    }),
    enabled: !!versionId,
  });
}
