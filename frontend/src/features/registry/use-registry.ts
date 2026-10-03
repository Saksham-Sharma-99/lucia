import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  getPlatformStatusOptions,
  listRegistryConnectorsOptions,
  listRegistryOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectorOut, PlatformStatus, RegistryEntryOut } from "@/api/generated/types.gen";
import { allOf, type QueryLike } from "@/lib/query";

export type Registry = {
  connectors: ConnectorOut[];
  rules: RegistryEntryOut[];
  channels: RegistryEntryOut[];
  tools: RegistryEntryOut[];
  models: string[];
  platform: PlatformStatus;
};

/**
 * Registry data the config forms need, as one query-shaped result (`data` once all three
 * requests succeed). It's static per deploy, so it's cached for the session.
 */
export function useRegistry(): QueryLike<Registry> {
  const all = allOf({
    connectors: useQuery({ ...listRegistryConnectorsOptions(), staleTime: Infinity }),
    entries: useQuery({ ...listRegistryOptions(), staleTime: Infinity }),
    platform: useQuery({ ...getPlatformStatusOptions(), staleTime: Infinity }),
  });
  const { connectors, entries, platform } = all.data ?? {};
  // Memoised on the cached responses so consumers get a stable object between renders.
  const data = useMemo(() => {
    if (!connectors || !entries || !platform) return undefined;
    const of = (kind: RegistryEntryOut["kind"]) => entries.filter((e) => e.kind === kind);
    return {
      connectors,
      rules: of("policy_rule"),
      channels: of("channel"),
      tools: of("tool"),
      models: platform.allowed_models,
      platform,
    };
  }, [connectors, entries, platform]);
  return { ...all, data };
}

export const ALERT_CHANNELS = [
  { value: "slack_dm", label: "Slack DM" },
  { value: "slack_thread", label: "Slack thread" },
  { value: "email", label: "Email" },
  { value: "digest", label: "Daily digest" },
  { value: "in_app", label: "In-app bell" },
] as const;
