import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import {
  diffAgentVersionsOptions,
  getAgentOptions,
  getAgentVersionOptions,
  switchMappingVersionMutation,
  updateMappingMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { MappingOut } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DiffView } from "@/features/agents/diff-view";
import { useRegistry } from "@/features/registry/use-registry";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { Problems, ShellDialog } from "./dialog-shell";
import { MappingEditor } from "./mapping-editor";
import { type MappingDraft } from "./model";

export function EditMappingDialog({
  mapping,
  onClose,
}: {
  mapping: MappingOut;
  onClose: () => void;
}) {
  const rules = useRegistry().data?.rules ?? [];
  const [draft, setDraft] = useState<MappingDraft>({
    identities: mapping.identities,
    overrides: mapping.overrides,
  });
  const version = useQuery(
    getAgentVersionOptions({ path: { handle: mapping.agent_handle, n: mapping.version } }),
  );
  const update = useApiMutation(
    { ...updateMappingMutation(), onSuccess: onClose },
    { stale: STALE.mapping, success: "Mapping saved", error: false },
  );
  return (
    <ShellDialog
      title={`Edit @${mapping.agent_handle} v${mapping.version}`}
      description={
        mapping.status === "active"
          ? "It's on: the checklist must still pass to save."
          : "It's off: you can save partial bindings."
      }
      onClose={onClose}
      footer={
        <Button
          disabled={update.isPending}
          onClick={() =>
            update.mutate({
              path: { mapping_id: mapping.id },
              body: { identities: draft.identities, overrides: draft.overrides },
            })
          }
        >
          Save mapping
        </Button>
      }
    >
      <QueryState
        query={version}
        what={`v${mapping.version}`}
        loading={<Skeleton className="h-40 w-full" />}
      >
        {(v) => (
          <MappingEditor
            firmId={mapping.firm_id}
            version={v}
            rules={rules}
            value={draft}
            onChange={setDraft}
          />
        )}
      </QueryState>
      <Problems error={update.error} />
    </ShellDialog>
  );
}

export function SwitchVersionDialog({
  mapping,
  initialVersionId,
  onClose,
}: {
  mapping: MappingOut;
  initialVersionId?: string;
  onClose: () => void;
}) {
  const agent = useQuery(getAgentOptions({ path: { handle: mapping.agent_handle } }));
  const options = (agent.data?.versions ?? []).filter(
    (v) => v.status === "active" && v.version !== mapping.version,
  );
  const [picked, setPicked] = useState(initialVersionId);
  const target = options.find((v) => v.id === picked) ?? options[0];
  const diff = useQuery({
    ...diffAgentVersionsOptions({
      path: { handle: mapping.agent_handle, a: mapping.version, b: target?.version ?? 0 },
    }),
    enabled: !!target,
  });
  const switchVersion = useApiMutation(
    {
      ...switchMappingVersionMutation(),
      onSuccess: (m) => {
        if (m.status === "active") toast.success(`Now running v${m.version}`);
        else
          toast.warning(
            `Switched to v${m.version}, but it's off: ${m.checklist_missing} connection(s) to bind`,
          );
        onClose();
      },
    },
    { stale: STALE.mapping, error: "Switch failed" },
  );
  return (
    <ShellDialog
      title={`Switch @${mapping.agent_handle} from v${mapping.version}`}
      description="Bindings and overrides carry over. The current mapping is kept, turned off, for the record."
      onClose={onClose}
      footer={
        <Button
          disabled={!target || switchVersion.isPending}
          onClick={() =>
            target &&
            switchVersion.mutate({
              path: { mapping_id: mapping.id },
              body: { agent_prompt_id: target.id },
            })
          }
        >
          {target ? `Switch to v${target.version}` : "Switch"}
        </Button>
      }
    >
      <QueryState
        query={agent}
        what={`@${mapping.agent_handle}`}
        loading={<Skeleton className="h-24 w-full" />}
      >
        {() =>
          options.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              There's no other active version to switch to.
            </p>
          ) : (
            <>
              <SimpleSelect
                label="Switch to version"
                value={target?.id}
                onChange={setPicked}
                options={options.map((v) => ({
                  value: v.id,
                  label: `v${v.version}${v.changelog ? ` · ${v.changelog.slice(0, 50)}` : ""}`,
                }))}
              />
              <QueryState
                query={diff}
                what="The changes"
                loading={<Skeleton className="h-24 w-full" />}
              >
                {(entries) => <DiffView entries={entries} />}
              </QueryState>
            </>
          )
        }
      </QueryState>
    </ShellDialog>
  );
}
