import { useQuery } from "@tanstack/react-query";
import { PlusIcon } from "lucide-react";
import { useEffect, useState } from "react";

import {
  listFirmsOptions,
  listMappingsOptions,
  updateMappingMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { FirmOut, MappingOut } from "@/api/generated/types.gen";
import { Avatar } from "@/components/shared/avatar";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { SimpleSelect } from "@/components/shared/controls";
import { EmptyState } from "@/components/shared/empty-state";
import { MoreButton } from "@/components/shared/more-button";
import { PageHeader } from "@/components/shared/page-header";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { CreateMappingDialog } from "./create-mapping-dialog";
import { EditMappingDialog, SwitchVersionDialog } from "./mapping-dialogs";
import { MappingsTable } from "./mappings-table";
import {
  type Confirm,
  confirmBody,
  confirmCopy,
  readLastFirm,
  rememberFirm,
  stateOf,
} from "./model";

/** The firm shown: the one in the URL, else the last one used, else the first. */
function pickFirm(firms: FirmOut[], requested?: string): FirmOut | undefined {
  return (
    firms.find((f) => f.id === requested) ?? firms.find((f) => f.id === readLastFirm()) ?? firms[0]
  );
}

export function MappingsPage({
  firm,
  page,
  onFirm,
  onPage,
}: {
  firm?: string;
  page: number;
  onFirm: (id: string) => void;
  onPage: (page: number) => void;
}) {
  const firms = useQuery(listFirmsOptions({ query: { status: "active", limit: 100 } }));
  const selected = pickFirm(firms.data?.items ?? [], firm);
  useEffect(() => {
    if (selected) rememberFirm(selected.id);
  }, [selected]);
  const total = firms.data?.total ?? 0;
  const shown = firms.data?.items.length ?? 0;
  return (
    <>
      <PageHeader
        title="Firm mappings"
        description="Which agent versions each firm runs, and with which connections."
        actions={
          shown > 0 && (
            <div className="flex flex-col items-end gap-1">
              <SimpleSelect
                label="Firm"
                className="w-64"
                value={selected?.id ?? null}
                placeholder="Pick a firm"
                onChange={onFirm}
                options={(firms.data?.items ?? []).map((f) => ({ value: f.id, label: f.name }))}
              />
              {total > shown && (
                <span className="text-muted-foreground text-xs">
                  Showing the first {shown} of {total} firms
                </span>
              )}
            </div>
          )
        }
      />
      <QueryState
        query={firms}
        what="Firms"
        isEmpty={(p) => p.total === 0}
        empty={
          <EmptyState
            title="No active firms"
            description="Add a firm first; mappings belong to a firm."
          />
        }
      >
        {() =>
          selected && <FirmMappings key={selected.id} firm={selected} page={page} onPage={onPage} />
        }
      </QueryState>
    </>
  );
}

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; mapping: MappingOut }
  | { kind: Confirm; mapping: MappingOut }
  | { kind: "switch"; mapping: MappingOut; versionId?: string }
  | null;

function FirmMappings({
  firm,
  page,
  onPage,
}: {
  firm: FirmOut;
  page: number;
  onPage: (page: number) => void;
}) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const mappings = useQuery(listMappingsOptions({ query: { firm_id: firm.id, page, limit: 20 } }));
  const update = useApiMutation(updateMappingMutation(), {
    stale: STALE.mapping,
    success: (m) => `@${m.agent_handle} is ${stateOf(m)}`,
  });
  const close = () => setDialog(null);
  const create = (
    <Button onClick={() => setDialog({ kind: "create" })}>
      <PlusIcon /> Map an agent
    </Button>
  );
  return (
    <>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 text-sm">
          <Avatar label={firm.name} color={firm.color} size="sm" />
          <span className="font-medium">{firm.name}</span>
        </div>
        {create}
      </div>
      <QueryState
        query={mappings}
        what="Mappings"
        isEmpty={(p) => p.total === 0}
        empty={
          <EmptyState
            title="No agents mapped to this firm"
            description="Map an agent version and bind it to this firm's connections."
            action={create}
          />
        }
      >
        {(p) => (
          <>
            <MappingsTable
              items={p.items}
              killSwitch={(m) => (
                <Switch
                  aria-label={`Kill switch for @${m.agent_handle}`}
                  checked={m.kill_switch}
                  onCheckedChange={() => setDialog({ kind: "kill", mapping: m })}
                />
              )}
              actions={(m) => (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={<MoreButton label={`Actions for @${m.agent_handle}`} />}
                  />
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => setDialog({ kind: "edit", mapping: m })}>
                      Edit connections and overrides
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => setDialog({ kind: "switch", mapping: m })}>
                      Switch version
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => setDialog({ kind: "toggle", mapping: m })}>
                      {m.status === "active" ? "Turn off" : "Turn on"}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            />
            <Pagination page={p.page} limit={p.limit} total={p.total} onPage={onPage} />
          </>
        )}
      </QueryState>
      {dialog?.kind === "create" && (
        <CreateMappingDialog
          firmId={firm.id}
          onClose={close}
          onSwitchInstead={(mapping, versionId) =>
            setDialog({ kind: "switch", mapping, versionId })
          }
        />
      )}
      {dialog?.kind === "edit" && <EditMappingDialog mapping={dialog.mapping} onClose={close} />}
      {dialog?.kind === "switch" && (
        <SwitchVersionDialog
          mapping={dialog.mapping}
          initialVersionId={dialog.versionId}
          onClose={close}
        />
      )}
      {(dialog?.kind === "kill" || dialog?.kind === "toggle") && (
        <ConfirmDialog
          open
          onOpenChange={(open) => open || close()}
          {...confirmCopy(dialog.kind, dialog.mapping, firm.name)}
          onConfirm={() =>
            update.mutate({
              path: { mapping_id: dialog.mapping.id },
              body: confirmBody(dialog.kind, dialog.mapping),
            })
          }
        />
      )}
    </>
  );
}
