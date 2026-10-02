import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { listAgentsOptions, listRunsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { ListRunsData } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { SearchInput } from "@/components/shared/search-input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { dateTime, relativeTime } from "@/lib/format";

import { FirmPicker } from "./firm-picker";
import { RUN_STATUSES, statusLabel } from "./model";
import { StatusPill } from "./status-pill";
import { useFirm } from "./use-firm";

export type RunsSearch = {
  firm?: string;
  agent?: string;
  status?: NonNullable<NonNullable<ListRunsData["query"]>["status"]>;
  q?: string;
  page: number;
};

/** Every run of a firm's agents, filterable; a row opens the run. */
export function RunsList({
  search,
  onSearch,
}: {
  search: RunsSearch;
  onSearch: (patch: Partial<RunsSearch>) => void;
}) {
  const navigate = useNavigate();
  const { firmId, firms, setFirm } = useFirm(search.firm);
  const agents = useQuery(listAgentsOptions({ query: { limit: 100 } }));
  const runs = useQuery({
    ...listRunsOptions({
      path: { firm_id: firmId ?? "" },
      query: {
        agent: search.agent,
        status: search.status,
        q: search.q,
        page: search.page,
        limit: 20,
      },
    }),
    enabled: !!firmId,
    placeholderData: keepPreviousData,
  });
  const noFirms = firms.isSuccess && (firms.data.items.length ?? 0) === 0;
  return (
    <>
      <PageHeader
        title="Agent runs"
        description="Every case an agent is working on, its tasks and where it stands."
      />
      {noFirms ? (
        <FirmPicker value={undefined} onChange={() => {}} />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <FirmPicker
              className="w-56"
              value={firmId}
              onChange={(id) => {
                setFirm(id);
                onSearch({ firm: id, page: 1 });
              }}
            />
            <SimpleSelect
              label="Agent"
              className="w-44"
              value={search.agent ?? "all"}
              onChange={(a) => onSearch({ agent: a === "all" ? undefined : a, page: 1 })}
              options={[
                { value: "all", label: "All agents" },
                ...(agents.data?.items ?? []).map((a) => ({
                  value: a.handle,
                  label: `@${a.handle}`,
                })),
              ]}
            />
            <SimpleSelect
              label="Status"
              className="w-52"
              value={search.status ?? "all"}
              onChange={(s) =>
                onSearch({
                  status: s === "all" ? undefined : (s as RunsSearch["status"]),
                  page: 1,
                })
              }
              options={[
                { value: "all", label: "All statuses" },
                ...RUN_STATUSES.map((s) => ({ value: s, label: statusLabel(s) })),
              ]}
            />
            <div className="w-64">
              <SearchInput
                label="Search subjects"
                placeholder="Search by subject"
                value={search.q}
                onCommit={(q) => onSearch({ q, page: 1 })}
              />
            </div>
          </div>
          {firmId && (
            <QueryState
              query={runs}
              what="Runs"
              isEmpty={(p) => p.total === 0}
              empty={
                <EmptyState
                  title={
                    search.q || search.agent || search.status ? "No runs match" : "No runs yet"
                  }
                  description="Runs start when someone asks an agent for something in the playground or Slack."
                />
              }
            >
              {(p) => (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Agent</TableHead>
                        <TableHead>Subject</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Tasks</TableHead>
                        <TableHead>Next wake-up</TableHead>
                        <TableHead>Started</TableHead>
                        <TableHead>Last activity</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {p.items.map((r) => (
                        <TableRow
                          key={r.id}
                          className="cursor-pointer"
                          onClick={() =>
                            void navigate({ to: "/runs/$runId", params: { runId: r.id } })
                          }
                        >
                          <TableCell className="font-medium">@{r.agent_handle}</TableCell>
                          <TableCell>{r.subject_title}</TableCell>
                          <TableCell>
                            <StatusPill status={r.status} />
                            {r.substatus && (
                              <p className="text-muted-foreground mt-0.5 text-xs">{r.substatus}</p>
                            )}
                          </TableCell>
                          <TableCell className="tabular-nums">
                            {r.tasks_done}/{r.tasks_total}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {r.next_wake_at ? relativeTime(r.next_wake_at) : "—"}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {dateTime(r.started_at)}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {relativeTime(r.updated_at ?? r.created_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <Pagination
                    page={p.page}
                    limit={p.limit}
                    total={p.total}
                    onPage={(n) => onSearch({ page: n })}
                  />
                </>
              )}
            </QueryState>
          )}
        </>
      )}
    </>
  );
}
