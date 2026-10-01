import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import type { MappingOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { StatusBadge } from "@/components/shared/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/format";

/** A firm's mappings, each linking to its detail page, with the kill switch and row actions. */
export function MappingsTable({
  items,
  killSwitch,
  actions,
}: {
  items: MappingOut[];
  killSwitch: (m: MappingOut) => ReactNode;
  actions: (m: MappingOut) => ReactNode;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead>Version</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Connections</TableHead>
          <TableHead>Kill switch</TableHead>
          <TableHead>Mapped</TableHead>
          <TableHead className="w-10" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((m) => (
          <TableRow
            key={m.id}
            className={m.status === "inactive" ? "text-muted-foreground" : undefined}
          >
            <TableCell>
              <Link
                to="/firm-mappings/$mappingId"
                params={{ mappingId: m.id }}
                search={{ tab: "overview" }}
                className="text-foreground font-mono text-sm hover:underline"
              >
                @{m.agent_handle}
              </Link>
              <span className="block text-sm">{m.agent_name}</span>
            </TableCell>
            <TableCell className="tabular-nums">v{m.version}</TableCell>
            <TableCell>
              <StatusBadge status={m.status} />
            </TableCell>
            <TableCell>
              <span className="flex items-center gap-1.5">
                {Object.keys(m.identities).map((c) => (
                  <ConnectorIcon key={c} connector={c} className="size-6" />
                ))}
                <span className={`text-xs ${m.checklist_ok ? "text-success" : "text-brass"}`}>
                  {m.checklist_ok ? "all bound" : `${m.checklist_missing} to bind`}
                </span>
              </span>
            </TableCell>
            <TableCell>{killSwitch(m)}</TableCell>
            <TableCell className="whitespace-nowrap">{relativeTime(m.mapped_at)}</TableCell>
            <TableCell>{actions(m)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
