import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { PlusIcon } from "lucide-react";

import { listAgentsOptions, listMappingsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { AgentListItem } from "@/api/generated/types.gen";
import { Avatar } from "@/components/shared/avatar";
import { EmptyState } from "@/components/shared/empty-state";
import { MoreButton } from "@/components/shared/more-button";
import { PageHeader } from "@/components/shared/page-header";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { QuickFilters } from "@/components/shared/quick-filters";
import { SearchInput } from "@/components/shared/search-input";
import { StatCards } from "@/components/shared/stat-cards";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { relativeTime } from "@/lib/format";

import { AgentActionsMenu } from "./agent-actions";

export type AgentsSearch = {
  q?: string;
  status?: "active" | "archived";
  templates?: boolean;
  page: number;
};

const PAGE_SIZE = 12; // a full 3-column grid

type View = "all" | "active" | "archived" | "templates";
const viewOf = (s: AgentsSearch): View => (s.templates ? "templates" : (s.status ?? "all"));
const searchFor: Record<View, Partial<AgentsSearch>> = {
  all: { status: undefined, templates: undefined },
  active: { status: "active", templates: undefined },
  archived: { status: "archived", templates: undefined },
  templates: { status: undefined, templates: true },
};

/** Totals for the stat cards and filter counts: each is a one-item page, read for its `total`. */
function useCounts() {
  const total = { select: (p: { total: number }) => p.total };
  const [active, archived, templates, mappings] = useQueries({
    queries: [
      { ...listAgentsOptions({ query: { status: "active", limit: 1 } }), ...total },
      { ...listAgentsOptions({ query: { status: "archived", limit: 1 } }), ...total },
      { ...listAgentsOptions({ query: { is_template: true, limit: 1 } }), ...total },
      { ...listMappingsOptions({ query: { status: "active", limit: 1 } }), ...total },
    ],
  }).map((q) => q.data);
  const all = active !== undefined && archived !== undefined ? active + archived : undefined;
  return { all, active, archived, templates, mappings };
}

export function AgentsList({
  search,
  onSearch,
}: {
  search: AgentsSearch;
  onSearch: (s: Partial<AgentsSearch>) => void;
}) {
  const agents = useQuery({
    ...listAgentsOptions({
      query: {
        q: search.q,
        status: search.status,
        is_template: !!search.templates,
        page: search.page,
        limit: PAGE_SIZE,
      },
    }),
    placeholderData: keepPreviousData,
  });
  const counts = useCounts();
  const view = viewOf(search);
  const filtered = !!(search.q || search.status);
  const newAgent = (
    <Button nativeButton={false} render={<Link to="/agents/new" search={{}} />}>
      <PlusIcon /> New agent
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description="Agents run for days or weeks. Each change saves a new version."
        actions={newAgent}
      />
      <StatCards
        stats={[
          { label: "Active agents", value: counts.active },
          { label: "Live mappings", value: counts.mappings },
          { label: "Templates", value: counts.templates },
          { label: "Archived", value: counts.archived },
        ]}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search agents"
          placeholder="Search name or description"
          value={search.q}
          onCommit={(q) => onSearch({ q, page: 1 })}
        />
        <QuickFilters
          label="Show"
          value={view}
          onChange={(v) => onSearch({ ...searchFor[v], page: 1 })}
          options={[
            { value: "all", label: "All", count: counts.all },
            { value: "active", label: "Active", count: counts.active },
            { value: "archived", label: "Archived", count: counts.archived },
            { value: "templates", label: "Templates", count: counts.templates },
          ]}
        />
      </div>
      <QueryState
        query={agents}
        what="Agents"
        isEmpty={(page) => page.total === 0}
        empty={
          filtered ? (
            <EmptyState title="No agents match" description="Try a different search or filter." />
          ) : (
            <EmptyState
              title={search.templates ? "No templates" : "No agents yet"}
              description="Start from a template like @records, or from a blank agent."
              action={newAgent}
            />
          )
        }
      >
        {(page) => (
          <>
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {page.items.map((a) => (
                <AgentCard key={a.id} agent={a} />
              ))}
            </ul>
            <Pagination
              page={page.page}
              limit={page.limit}
              total={page.total}
              onPage={(p) => onSearch({ page: p })}
            />
          </>
        )}
      </QueryState>
    </>
  );
}

/** The whole card opens the agent (a stretched link); the menu sits above that link. */
function AgentCard({ agent: a }: { agent: AgentListItem }) {
  const firms = a.active_mapping_count;
  return (
    <li className="bg-card hover:border-brass/60 relative flex flex-col gap-3 rounded-xl border p-4 transition-colors">
      <div className="flex items-start gap-3">
        <Avatar label={a.name} colorKey={a.handle} />
        <div className="min-w-0 flex-1">
          <Link
            to="/agents/$handle"
            params={{ handle: a.handle }}
            search={{ tab: "overview" }}
            className="block truncate font-mono text-sm font-semibold after:absolute after:inset-0 after:rounded-xl"
          >
            @{a.handle}
          </Link>
          <p className="text-muted-foreground truncate text-sm">{a.name}</p>
        </div>
        <StatusBadge status={a.is_template ? "template" : a.status} />
        <div className="relative -mt-1 -mr-2">
          <AgentActionsMenu
            agent={a}
            amendFrom={a.latest_version}
            trigger={<MoreButton label={`Actions for @${a.handle}`} />}
          />
        </div>
      </div>
      <p className="text-muted-foreground line-clamp-2 text-sm">
        {a.description || "No description"}
      </p>
      <p className="text-muted-foreground mt-auto font-mono text-xs">
        v{a.latest_version} · {firms} {firms === 1 ? "firm" : "firms"} · updated{" "}
        {relativeTime(a.updated_at)}
      </p>
    </li>
  );
}
