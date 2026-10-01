import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  createMappingMutation,
  getAgentOptions,
  getAgentVersionOptions,
  listAgentsOptions,
  listMappingsOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { MappingOut } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useRegistry } from "@/features/registry/use-registry";
import { STALE } from "@/lib/invalidate";
import { isProblem } from "@/lib/problem";
import { allOf } from "@/lib/query";
import { useApiMutation } from "@/lib/use-api-mutation";

import { Problems, ShellDialog } from "./dialog-shell";
import { useChecklist } from "./hooks";
import { MappingEditor } from "./mapping-editor";
import { bindingsFor, type MappingDraft } from "./model";

const EMPTY: MappingDraft = { identities: {}, overrides: {} };

/**
 * Map an agent version to this firm. Mount it only while open, so every open starts clean.
 * A 409 "already active" offers to switch the existing mapping's version instead.
 */
export function CreateMappingDialog({
  firmId,
  onClose,
  onSwitchInstead,
}: {
  firmId: string;
  onClose: () => void;
  onSwitchInstead: (m: MappingOut, versionId: string) => void;
}) {
  const rules = useRegistry().data?.rules ?? [];
  const [handle, setHandle] = useState<string | null>(null);
  const [versionN, setVersionN] = useState<number | null>(null);
  const [draft, setDraft] = useState<MappingDraft>(EMPTY);
  const [activate, setActivate] = useState(false);
  const agents = useQuery(
    listAgentsOptions({ query: { status: "active", limit: 100, sort: "handle" } }),
  );
  const agent = useQuery({
    ...getAgentOptions({ path: { handle: handle ?? "" } }),
    enabled: !!handle,
  });
  const activeVersions = (agent.data?.versions ?? []).filter((v) => v.status === "active");
  const n = versionN ?? activeVersions[0]?.version;
  const version = useQuery({
    ...getAgentVersionOptions({ path: { handle: handle ?? "", n: n ?? 0 } }),
    enabled: !!handle && !!n,
  });
  const identities = version.data ? bindingsFor(version.data, draft.identities) : {};
  const checklist = useChecklist(firmId, version.data?.id, identities);
  const ready = !!checklist.data?.length && checklist.data.every((i) => i.ok);
  const turnOn = activate && ready;
  const create = useApiMutation(
    { ...createMappingMutation(), onSuccess: onClose },
    {
      stale: STALE.mapping,
      success: (m) =>
        `Mapped @${m.agent_handle} v${m.version}${m.status === "active" ? " and turned it on" : ""}`,
      error: false,
    },
  );
  const conflict = isProblem(create.error) && create.error.status === 409;
  // The mapping a 409 collided with, to offer switching its version instead.
  const active = useQuery({
    ...listMappingsOptions({
      query: { firm_id: firmId, agent_id: agent.data?.id, status: "active", limit: 1 },
    }),
    enabled: conflict && !!agent.data,
  });
  // Only worth offering when it runs another version; otherwise there's nothing to switch.
  const current = active.data?.items.find((m) => m.agent_prompt_id !== version.data?.id);

  const pickAgent = (h: string) => {
    setHandle(h);
    setVersionN(null);
    setDraft(EMPTY);
  };
  // Overrides are tied to the version's follow-up and pack, so a new version starts without them.
  const pickVersion = (v: string) => {
    setVersionN(Number(v));
    setDraft((d) => ({ ...d, overrides: {} }));
  };
  const switchInstead = () => {
    if (!current || !version.data) return;
    onClose();
    onSwitchInstead(current, version.data.id);
  };
  const submit = () => {
    if (!version.data) return;
    create.mutate({
      body: {
        firm_id: firmId,
        agent_prompt_id: version.data.id,
        identities,
        overrides: draft.overrides,
        activate: turnOn,
      },
    });
  };

  return (
    <ShellDialog
      title="Map an agent to this firm"
      description="The firm runs the version you pick until you switch it."
      onClose={onClose}
      footer={
        <Button disabled={!version.data || create.isPending} onClick={submit}>
          {create.isPending ? "Mapping…" : turnOn ? "Map and turn on" : "Map agent"}
        </Button>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel>Agent</FieldLabel>
          <QueryState query={agents} what="Agents" loading={<Skeleton className="h-9 w-full" />}>
            {(list) => (
              <>
                <SimpleSelect
                  label="Agent"
                  value={handle}
                  placeholder="Pick an agent"
                  onChange={pickAgent}
                  options={list.items.map((a) => ({
                    value: a.handle,
                    label: `@${a.handle} · ${a.name}`,
                  }))}
                />
                {list.total > list.items.length && (
                  <p className="text-muted-foreground text-xs">
                    Showing the first {list.items.length} of {list.total} agents by handle.
                  </p>
                )}
              </>
            )}
          </QueryState>
        </Field>
        <Field>
          <FieldLabel>Version</FieldLabel>
          <SimpleSelect
            label="Version"
            value={n ? String(n) : null}
            disabled={!handle}
            placeholder="Pick a version"
            onChange={pickVersion}
            options={activeVersions.map((v) => ({
              value: String(v.version),
              label: `v${v.version}${v.changelog ? ` · ${v.changelog.slice(0, 40)}` : ""}`,
            }))}
          />
        </Field>
      </div>
      {agent.data && !activeVersions.length ? (
        <p className="text-muted-foreground text-sm">This agent has no active version to map.</p>
      ) : (
        handle && (
          <QueryState
            query={allOf({ agent, version })}
            what={`@${handle}`}
            loading={<Skeleton className="h-32 w-full" />}
          >
            {({ version: v }) => (
              <>
                <MappingEditor
                  firmId={firmId}
                  version={v}
                  rules={rules}
                  value={{ ...draft, identities }}
                  onChange={setDraft}
                />
                <label className="flex items-center gap-3 text-sm">
                  <Switch checked={turnOn} disabled={!ready} onCheckedChange={setActivate} />
                  Turn on now
                  {checklist.isError ? (
                    <span className="text-destructive">
                      Couldn't check the connections.{" "}
                      <button
                        type="button"
                        className="underline"
                        onClick={() => void checklist.refetch()}
                      >
                        Try again
                      </button>
                    </span>
                  ) : checklist.isPending ? (
                    <span className="text-muted-foreground">Checking the connections…</span>
                  ) : (
                    !ready && (
                      <span className="text-muted-foreground">Bind every connection first.</span>
                    )
                  )}
                </label>
              </>
            )}
          </QueryState>
        )
      )}
      <Problems error={create.error} />
      {conflict && current && version.data && (
        <Button variant="outline" onClick={switchInstead}>
          Switch v{current.version} to v{version.data.version} instead
        </Button>
      )}
    </ShellDialog>
  );
}
