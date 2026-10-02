import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { BriefcaseIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import {
  listSubjectKindsOptions,
  listSubjectsOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { SubjectOut } from "@/api/generated/types.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { QuickFilters } from "@/components/shared/quick-filters";
import { SearchInput } from "@/components/shared/search-input";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { relativeTime } from "@/lib/format";

type Status = "all" | "open" | "closed";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A firm's subjects (matters, leads…): the things its agents work on, as cards. */
export function SubjectsTab({
  firmId,
  onOpen,
}: {
  firmId: string;
  onOpen: (subjectId: string) => void;
}) {
  const [q, setQ] = useState<string>();
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState<Status>("all");
  const [pageNo, setPage] = useState(1);
  const kinds = useQuery(listSubjectKindsOptions({ path: { firm_id: firmId } }));
  const subjects = useQuery({
    ...listSubjectsOptions({
      path: { firm_id: firmId },
      query: {
        q,
        kind: kind === "all" ? undefined : kind,
        status: status === "all" ? undefined : status,
        page: pageNo,
        limit: 24,
      },
    }),
    placeholderData: keepPreviousData,
  });
  const filtered = !!q || kind !== "all" || status !== "all";
  const add = (
    <Button onClick={() => onOpen("new")}>
      <PlusIcon /> New subject
    </Button>
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-72">
          <SearchInput
            label="Search subjects"
            placeholder="Search title, reference or contact"
            value={q}
            onCommit={(next) => {
              setQ(next);
              setPage(1);
            }}
          />
        </div>
        {(kinds.data?.length ?? 0) > 0 && (
          <QuickFilters
            label="Kind"
            value={kind}
            onChange={(k) => {
              setKind(k);
              setPage(1);
            }}
            options={[
              { value: "all", label: "All kinds" },
              ...(kinds.data ?? []).map((k) => ({ value: k, label: k })),
            ]}
          />
        )}
        <QuickFilters<Status>
          label="Status"
          value={status}
          onChange={(s) => {
            setStatus(s);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All" },
            { value: "open", label: "Open" },
            { value: "closed", label: "Closed" },
          ]}
        />
        <div className="ml-auto">{add}</div>
      </div>
      <QueryState
        query={subjects}
        what="Subjects"
        isEmpty={(p) => p.total === 0}
        empty={
          filtered ? (
            <EmptyState title="No subjects match" />
          ) : (
            <EmptyState
              title="No subjects yet"
              description="A subject is what an agent works on: a matter, a lead, a patient case. Add one with its contacts."
              action={add}
            />
          )
        }
      >
        {(p) => (
          <>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {p.items.map((s) => (
                <li key={s.id}>
                  <SubjectCard subject={s} onOpen={() => onOpen(s.id)} />
                </li>
              ))}
            </ul>
            <Pagination page={p.page} limit={p.limit} total={p.total} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}

function SubjectCard({ subject: s, onOpen }: { subject: SubjectOut; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="bg-card hover:border-foreground/20 flex h-full w-full flex-col gap-3 rounded-lg border p-4 text-left transition-colors"
    >
      <div className="flex items-start gap-3">
        <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
          <BriefcaseIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{s.title}</p>
          {s.external_ref && (
            <p className="text-muted-foreground truncate font-mono text-xs">{s.external_ref}</p>
          )}
        </div>
        <StatusBadge status={s.status} />
      </div>
      <div className="text-muted-foreground mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <Badge variant="secondary">{s.kind}</Badge>
        <span>{plural(s.contact_count ?? 0, "contact")}</span>
        <span>{plural(s.live_run_count ?? 0, "live run")}</span>
        <span className="ml-auto">{relativeTime(s.updated_at ?? s.created_at)}</span>
      </div>
    </button>
  );
}
