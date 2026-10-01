import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { PencilLineIcon } from "lucide-react";
import { type ReactNode } from "react";

import { getAgentOptions, getAgentVersionOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { AgentDetail as Agent, VersionDetail } from "@/api/generated/types.gen";
import { Avatar } from "@/components/shared/avatar";
import { SimpleSelect } from "@/components/shared/controls";
import { EmptyState } from "@/components/shared/empty-state";
import { MoreButton } from "@/components/shared/more-button";
import { QueryState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRegistry, type Registry } from "@/features/registry/use-registry";
import { allOf } from "@/lib/query";

import { AgentActionsMenu } from "./agent-actions";
import { type ConfigForm } from "./config";
import { AGENT_TABS, type AgentTab, type SectionId } from "./editor";
import { OverviewTab } from "./overview-tab";
import { ReadOnlyConfig } from "./read-only-config";
import { SECTION_VIEWS } from "./section-views";
import { VersionsTab } from "./versions-tab";

const TAB_LABEL: Record<AgentTab, string> = {
  overview: "Overview",
  prompt: "Prompt",
  capabilities: "Capabilities",
  policies: "Policies",
  schedules: "Schedules",
  evals: "Evals",
  versions: "Versions",
};
type Change = { tab?: AgentTab; v?: number };

export function AgentDetailPage({
  handle,
  tab,
  v,
  onChange,
}: {
  handle: string;
  tab: AgentTab;
  v?: number;
  onChange: (s: Change) => void;
}) {
  const agent = useQuery(getAgentOptions({ path: { handle } }));
  return (
    <QueryState query={agent} what={`@${handle}`} loading={<Skeleton className="h-96 w-full" />}>
      {(a) => <Detail agent={a} version={v ?? defaultVersion(a)} tab={tab} onChange={onChange} />}
    </QueryState>
  );
}

/** The newest active version, else the newest. Agents are created with v1, so one exists. */
function defaultVersion(agent: Agent): number {
  const newest = [...agent.versions].sort((x, y) => y.version - x.version);
  return (newest.find((x) => x.status === "active") ?? newest[0]).version;
}

type View = { agent: Agent; version: VersionDetail; config: ConfigForm; registry: Registry };

const readOnly =
  (id: SectionId) =>
  ({ registry }: View) =>
    SECTION_VIEWS[id]({ registry, disabled: true });

/** Tabs that show a version's config. Versions and Evals don't need it, so they aren't here. */
const CONFIG_VIEWS: Partial<Record<AgentTab, (v: View) => ReactNode>> = {
  overview: (v) => <OverviewTab {...v} />,
  prompt: readOnly("prompt"),
  capabilities: readOnly("capabilities"),
  policies: readOnly("policies"),
  schedules: readOnly("schedules"),
};

function Detail({
  agent,
  version,
  tab,
  onChange,
}: {
  agent: Agent;
  version: number;
  tab: AgentTab;
  onChange: (s: Change) => void;
}) {
  // Only the config tabs need the version's config and the registry; Versions and Evals don't.
  const config = allOf({
    detail: useQuery(getAgentVersionOptions({ path: { handle: agent.handle, n: version } })),
    registry: useRegistry(),
  });
  const view = CONFIG_VIEWS[tab];
  const archived = agent.status === "archived";
  const viewingArchived = agent.versions.find((x) => x.version === version)?.status === "archived";

  return (
    // On the overview, the page fills the viewport (less main's padding) so its two panes
    // can scroll on their own; other tabs scroll with the page.
    <div
      className={tab === "overview" ? "lg:flex lg:h-[calc(100dvh-4rem)] lg:flex-col" : undefined}
    >
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <Avatar label={agent.name} colorKey={agent.handle} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-[1.375rem] leading-tight font-semibold">
                @{agent.handle}
              </h1>
              <StatusBadge status={agent.status} />
              {agent.is_template && <StatusBadge status="template" />}
            </div>
            <p className="mt-0.5 font-medium">{agent.name}</p>
            <p className="text-muted-foreground max-w-prose text-sm">{agent.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <SimpleSelect
            label="Version"
            className="w-40"
            value={String(version)}
            onChange={(n) => onChange({ v: Number(n) })}
            options={agent.versions.map((x) => ({
              value: String(x.version),
              label: `v${x.version} · ${x.status}`,
            }))}
          />
          <Button
            disabled={archived}
            nativeButton={false}
            render={
              <Link
                to="/agents/$handle/amend"
                params={{ handle: agent.handle }}
                search={{ from: version }}
              />
            }
          >
            <PencilLineIcon /> Amend v{version}
          </Button>
          <AgentActionsMenu
            agent={agent}
            trigger={<MoreButton label="More actions" variant="outline" size="icon" />}
          />
        </div>
      </header>
      {viewingArchived && !archived && (
        <p className="text-brass mb-4 text-sm">
          You're viewing an archived version. Mappings can't use it until it's reactivated.
        </p>
      )}

      <Tabs
        value={tab}
        onValueChange={(t) => onChange({ tab: t as AgentTab })}
        className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col"
      >
        <TabsList variant="line" className="mb-6">
          {AGENT_TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {TAB_LABEL[t]}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="evals">
          <EmptyState
            title="Evals are coming soon"
            description="Simulated runs of this agent, scored against expected outcomes, will land here."
          />
        </TabsContent>
        <TabsContent value="versions">
          <VersionsTab agent={agent} onView={(n) => onChange({ v: n, tab: "overview" })} />
        </TabsContent>
        {view && (
          <QueryState
            query={config}
            what={`v${version}`}
            loading={<Skeleton className="h-64 w-full" />}
          >
            {({ detail, registry }) => (
              <ReadOnlyConfig config={detail.config}>
                {(config) => view({ agent, version: detail, config, registry })}
              </ReadOnlyConfig>
            )}
          </QueryState>
        )}
      </Tabs>
    </div>
  );
}
