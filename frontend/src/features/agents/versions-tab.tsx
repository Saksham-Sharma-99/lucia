import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import {
  archiveAgentVersionMutation,
  diffAgentVersionsOptions,
  unarchiveAgentVersionMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { AgentDetail, VersionSummary } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { MoreButton } from "@/components/shared/more-button";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { DiffView } from "./diff-view";

export function VersionsTab({
  agent,
  onView,
}: {
  agent: AgentDetail;
  onView: (n: number) => void;
}) {
  const versions = agent.versions;
  const [a, setA] = useState(versions[1]?.version ?? versions[0]?.version);
  const [b, setB] = useState(versions[0]?.version);
  const [comparing, setComparing] = useState(false);
  const options = versions.map((v) => ({ value: String(v.version), label: `v${v.version}` }));

  return (
    <div className="space-y-6">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Version</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Note</TableHead>
            <TableHead>Saved by</TableHead>
            <TableHead>Saved</TableHead>
            <TableHead className="text-right">Active mappings</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.map((v) => (
            <TableRow key={v.id}>
              <TableCell className="font-medium tabular-nums">v{v.version}</TableCell>
              <TableCell>
                <StatusBadge status={v.status} />
              </TableCell>
              <TableCell className="text-muted-foreground max-w-xs truncate">
                {v.changelog || "—"}
              </TableCell>
              <TableCell>{v.created_by_name}</TableCell>
              <TableCell className="text-muted-foreground whitespace-nowrap">
                {relativeTime(v.created_at)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{v.mapping_count}</TableCell>
              <TableCell>
                <VersionMenu agent={agent} version={v} onView={onView} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {versions.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          Compare
          <SimpleSelect
            label="Compare from"
            className="w-24 min-w-24"
            value={String(a)}
            onChange={(v) => setA(Number(v))}
            options={options}
          />
          with
          <SimpleSelect
            label="Compare to"
            className="w-24 min-w-24"
            value={String(b)}
            onChange={(v) => setB(Number(v))}
            options={options}
          />
          <Button variant="outline" size="sm" disabled={a === b} onClick={() => setComparing(true)}>
            Show changes
          </Button>
        </div>
      )}
      <Sheet open={comparing} onOpenChange={setComparing}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>
              v{a} → v{b}
            </SheetTitle>
            <SheetDescription>What changed in the config of @{agent.handle}.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{comparing && <Diff handle={agent.handle} a={a} b={b} />}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Diff({ handle, a, b }: { handle: string; a: number; b: number }) {
  const diff = useQuery(diffAgentVersionsOptions({ path: { handle, a, b } }));
  if (diff.isPending) return <p className="text-muted-foreground text-sm">Loading…</p>;
  if (diff.isError) return <p className="text-destructive text-sm">Couldn't load the diff.</p>;
  return <DiffView entries={diff.data} />;
}

function VersionMenu({
  agent,
  version,
  onView,
}: {
  agent: AgentDetail;
  version: VersionSummary;
  onView: (n: number) => void;
}) {
  const navigate = useNavigate();
  const path = { handle: agent.handle, n: version.version };
  const archive = useApiMutation(archiveAgentVersionMutation(), {
    stale: STALE.agent,
    success: `Archived v${version.version}`,
  });
  const unarchive = useApiMutation(unarchiveAgentVersionMutation(), {
    stale: STALE.agent,
    success: `Reactivated v${version.version}`,
  });
  const inUse = version.mapping_count > 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<MoreButton label={`Actions for v${version.version}`} />} />
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onView(version.version)}>View</DropdownMenuItem>
        <DropdownMenuItem
          disabled={agent.status === "archived"}
          onClick={() =>
            void navigate({
              to: "/agents/$handle/amend",
              params: { handle: agent.handle },
              search: { from: version.version },
            })
          }
        >
          Amend from this version
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {version.status === "active" ? (
          <DropdownMenuItem disabled={inUse} onClick={() => archive.mutate({ path })}>
            {inUse ? "In use by a mapping" : "Archive"}
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onClick={() => unarchive.mutate({ path })}>Reactivate</DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
