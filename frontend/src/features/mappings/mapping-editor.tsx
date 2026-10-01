import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CheckCircle2Icon, CircleIcon } from "lucide-react";

import { listConnectionsOptions } from "@/api/generated/@tanstack/react-query.gen";
import type {
  Overrides,
  PolicyRuleRef,
  RegistryEntryOut,
  VersionDetail,
} from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { CheckboxGroup, NumberInput, SimpleSelect } from "@/components/shared/controls";
import { SchemaField } from "@/components/shared/policy-rule-form";
import { Switch } from "@/components/ui/switch";
import { ALERT_CHANNELS } from "@/features/registry/use-registry";
import { CONNECTOR_NAMES } from "@/lib/connectors";
import { hours } from "@/lib/format";
import { label, orderedProperties, type Params, type Schema } from "@/lib/json-schema";

import { useChecklist } from "./hooks";
import { baseMinWait, type MappingDraft } from "./model";

type Routing = NonNullable<Overrides["alert_routing"]>;
const DEFAULT_ROUTING: Routing = { P0: ["slack_dm"], P1: ["slack_thread"], P2: ["digest"] };

/** Bindings (one connection per connector the version uses), live checklist and overrides. */
export function MappingEditor({
  firmId,
  version,
  rules,
  value,
  onChange,
}: {
  firmId: string;
  version: VersionDetail;
  rules: RegistryEntryOut[];
  value: MappingDraft;
  onChange: (v: MappingDraft) => void;
}) {
  const set = (overrides: Partial<Overrides>) =>
    onChange({ ...value, overrides: { ...value.overrides, ...overrides } });
  const pack = (version.config.policy_pack ?? []).filter((p) => Object.keys(p.params ?? {}).length);
  return (
    <div className="space-y-6">
      <Bindings
        firmId={firmId}
        version={version}
        identities={value.identities}
        onChange={(identities) => onChange({ ...value, identities })}
      />
      <details className="rounded-lg border px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold">
          Firm-specific overrides (optional)
        </summary>
        <p className="text-muted-foreground mt-1 text-sm">
          Overrides can only make the agent stricter than its version and the firm's policy floor.
        </p>
        <div className="mt-4 space-y-5">
          <CadenceOverride
            base={baseMinWait(version)}
            value={value.overrides.cadence?.min_wait_hours}
            onChange={(h) => set({ cadence: h === null ? null : { min_wait_hours: h } })}
          />
          <AlertRoutingOverride
            value={value.overrides.alert_routing ?? null}
            onChange={(alert_routing) => set({ alert_routing })}
          />
          {pack.map((ref) => (
            <PolicyOverride
              key={ref.rule}
              base={ref}
              rule={rules.find((r) => r.name === ref.rule)}
              value={value.overrides.policy_params?.[ref.rule]}
              onChange={(params) => {
                const next = { ...value.overrides.policy_params };
                if (params) next[ref.rule] = params;
                else delete next[ref.rule];
                set({ policy_params: Object.keys(next).length ? next : null });
              }}
            />
          ))}
        </div>
      </details>
    </div>
  );
}

function Bindings({
  firmId,
  version,
  identities,
  onChange,
}: {
  firmId: string;
  version: VersionDetail;
  identities: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
}) {
  const connections = useQuery(listConnectionsOptions({ path: { firm_id: firmId } }));
  const checklist = useChecklist(firmId, version.id, identities);
  const items = new Map((checklist.data ?? []).map((i) => [i.connector, i]));
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Connections</h3>
      <p className="text-muted-foreground text-sm">
        Pick which of this firm's connections the agent uses for each app.{" "}
        <Link
          to="/firms/$firmId"
          params={{ firmId }}
          search={{ tab: "connections" }}
          className="text-foreground underline"
        >
          Add a connection
        </Link>
      </p>
      <ul className="divide-border divide-y rounded-lg border">
        {version.config.capabilities.map(({ connector }) => {
          const item = items.get(connector);
          const options = (connections.data ?? [])
            .filter((c) => c.connector === connector)
            .map((c) => ({ value: c.id, label: `${c.label} · ${c.status}` }));
          return (
            <li key={connector} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
              <ConnectorIcon connector={connector} />
              <span className="w-28 text-sm">{CONNECTOR_NAMES[connector] ?? connector}</span>
              <SimpleSelect
                label={`${CONNECTOR_NAMES[connector] ?? connector} connection`}
                className="w-64"
                value={identities[connector] ?? null}
                placeholder={options.length ? "Pick a connection" : "No connections yet"}
                disabled={!options.length}
                options={options}
                onChange={(id) => onChange({ ...identities, [connector]: id })}
              />
              <span
                className={`flex items-center gap-1.5 text-xs ${item?.ok ? "text-success" : "text-muted-foreground"}`}
              >
                {item?.ok ? (
                  <CheckCircle2Icon className="size-3.5" />
                ) : (
                  <CircleIcon className="size-3.5" />
                )}
                {item?.reason ?? "Checking…"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Minimum wait between contacts; it can only be raised above the version's. */
function CadenceOverride({
  base,
  value,
  onChange,
}: {
  base: number;
  value: number | undefined;
  onChange: (h: number | null) => void;
}) {
  const on = value !== undefined;
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Switch
        aria-label="Override follow-up cadence"
        checked={on}
        onCheckedChange={(checked) => onChange(checked ? base : null)}
      />
      Wait at least
      <NumberInput
        aria-label="Minimum wait in hours"
        className="w-20"
        min={base}
        disabled={!on}
        value={value ?? base}
        onChange={onChange}
      />
      hours between contacts
      <span className="text-muted-foreground">(version: {hours(base)}; can only go up)</span>
    </div>
  );
}

function AlertRoutingOverride({
  value,
  onChange,
}: {
  value: Routing | null;
  onChange: (v: Routing | null) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-3 text-sm">
        <Switch checked={!!value} onCheckedChange={(on) => onChange(on ? DEFAULT_ROUTING : null)} />
        Route alerts differently at this firm
      </label>
      {value &&
        (["P0", "P1", "P2"] as const).map((u) => (
          <div key={u} className="flex items-center gap-4 pl-12">
            <span className="w-8 text-sm font-medium">{u}</span>
            <CheckboxGroup
              value={value[u] ?? []}
              options={ALERT_CHANNELS}
              onChange={(ch) => onChange({ ...value, [u]: ch })}
            />
          </div>
        ))}
    </div>
  );
}

/** Tighten one rule from the version's pack; starts from the version's params. */
function PolicyOverride({
  base,
  rule,
  value,
  onChange,
}: {
  base: PolicyRuleRef;
  rule?: RegistryEntryOut;
  value?: Params;
  onChange: (v: Params | null) => void;
}) {
  const schema = (rule?.params_schema ?? {}) as Schema;
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-3 text-sm">
        <Switch
          checked={!!value}
          onCheckedChange={(on) => onChange(on ? { ...base.params } : null)}
        />
        Tighten “{rule?.display_name ?? base.rule}”
        <span className="text-muted-foreground font-mono text-xs">
          version: {JSON.stringify(base.params)}
        </span>
      </label>
      {value &&
        orderedProperties(schema).map(([key, prop]) => (
          <div key={key} className="flex items-center gap-3 pl-12 text-sm">
            <span className="text-muted-foreground w-24">{label(key)}</span>
            <SchemaField
              label={label(key)}
              schema={prop}
              value={value[key]}
              onChange={(v) => onChange({ ...value, [key]: v })}
            />
          </div>
        ))}
    </div>
  );
}
