import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import {
  getAgentVersionOptions,
  getMappingOptions,
  getMappingResolvedOptions,
  listConnectionsOptions,
  updateMappingMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type {
  MappingOut,
  MappingResolved,
  PolicySource,
  ResolvedPolicy,
} from "@/api/generated/types.gen";
import { Avatar } from "@/components/shared/avatar";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { QueryState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toForm } from "@/features/agents/config";
import { type AtFirm, OrchestrationDiagram } from "@/features/agents/orchestration-diagram";
import { ReadOnlyConfig } from "@/features/agents/read-only-config";
import { SECTION_VIEWS } from "@/features/agents/section-views";
import { DAYS } from "@/features/firms/model";
import { ALERT_CHANNELS, useRegistry } from "@/features/registry/use-registry";
import { CONNECTOR_NAMES } from "@/lib/connectors";
import { dateTime, hours, relativeTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { label } from "@/lib/json-schema";
import { allOf } from "@/lib/query";
import { useApiMutation } from "@/lib/use-api-mutation";

import { useChecklist } from "./hooks";
import { confirmBody, confirmCopy, MAPPING_TABS, type MappingTab, stateOf } from "./model";

const TAB_LABEL: Record<MappingTab, string> = {
  overview: "Overview",
  policies: "Policies and guardrails",
  capabilities: "Capabilities",
  prompt: "Prompt and models",
  schedules: "Schedules",
  history: "History",
};
const SOURCE_LABEL = {
  version: "Agent version",
  firm: "Firm policy floor",
  mapping: "This mapping",
};
const CHANNEL_LABEL: Record<string, string> = Object.fromEntries(
  ALERT_CHANNELS.map((c) => [c.value, c.label]),
);

/** A mapping as the firm runs it: the pinned version, plus the firm's rules layered on top. */
export function MappingDetailPage({
  mappingId,
  tab,
  onTab,
}: {
  mappingId: string;
  tab: MappingTab;
  onTab: (t: MappingTab) => void;
}) {
  const mapping = useQuery(getMappingOptions({ path: { mapping_id: mappingId } }));
  return (
    <QueryState query={mapping} what="This mapping" loading={<Skeleton className="h-96 w-full" />}>
      {(m) => <Detail mapping={m} tab={tab} onTab={onTab} />}
    </QueryState>
  );
}

function Detail({
  mapping: m,
  tab,
  onTab,
}: {
  mapping: MappingOut;
  tab: MappingTab;
  onTab: (t: MappingTab) => void;
}) {
  const data = allOf({
    resolved: useQuery(getMappingResolvedOptions({ path: { mapping_id: m.id } })),
    version: useQuery(getAgentVersionOptions({ path: { handle: m.agent_handle, n: m.version } })),
    registry: useRegistry(),
  });
  return (
    // Like the agent page: on the overview, the panes fill the viewport and scroll on their own.
    <div
      className={tab === "overview" ? "lg:flex lg:h-[calc(100dvh-4rem)] lg:flex-col" : undefined}
    >
      <header className="mb-6 flex flex-wrap items-start gap-4">
        <Avatar label={m.agent_name} colorKey={m.agent_handle} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="font-mono text-[1.375rem] leading-tight font-semibold">
              @{m.agent_handle} v{m.version}
            </h1>
            <StatusBadge status={m.status} />
            {m.kill_switch && <StatusBadge status="stopped" />}
          </div>
          <p className="text-muted-foreground text-sm">
            {m.agent_name} at{" "}
            <Link
              to="/firms/$firmId"
              params={{ firmId: m.firm_id }}
              search={{ tab: "overview" }}
              className="text-foreground underline"
            >
              {m.firm_name}
            </Link>
          </p>
        </div>
        <KillSwitch mapping={m} />
      </header>
      <Tabs
        value={tab}
        onValueChange={(t) => onTab(t as MappingTab)}
        className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col"
      >
        <TabsList variant="line" className="mb-6">
          {MAPPING_TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {TAB_LABEL[t]}
            </TabsTrigger>
          ))}
        </TabsList>
        <QueryState query={data} what="Its settings" loading={<Skeleton className="h-64 w-full" />}>
          {({ resolved, version, registry }) => (
            <>
              <TabsContent value="overview" className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
                <Overview
                  mapping={m}
                  versionId={version.id}
                  diagram={
                    <OrchestrationDiagram
                      handle={m.agent_handle}
                      config={toForm(version.config)}
                      registry={registry}
                      atFirm={atFirm(resolved)}
                    />
                  }
                />
              </TabsContent>
              <TabsContent value="policies">
                <Guardrails resolved={resolved} />
              </TabsContent>
              <TabsContent value="history">
                <History mapping={m} resolved={resolved} />
              </TabsContent>
              {(["capabilities", "prompt", "schedules"] as const).map((id) => (
                <TabsContent key={id} value={id}>
                  <ReadOnlyConfig config={version.config}>
                    {() => SECTION_VIEWS[id]({ registry, disabled: true })}
                  </ReadOnlyConfig>
                </TabsContent>
              ))}
            </>
          )}
        </QueryState>
      </Tabs>
    </div>
  );
}

/** The kill switch, confirmed first; the dialog closes once the change is saved. */
function KillSwitch({ mapping: m }: { mapping: MappingOut }) {
  const [confirming, setConfirming] = useState(false);
  const update = useApiMutation(updateMappingMutation(), {
    stale: STALE.mapping,
    success: (saved) => `@${saved.agent_handle} is ${stateOf(saved)}`,
  });
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch checked={m.kill_switch} onCheckedChange={() => setConfirming(true)} />
      Kill switch
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        {...confirmCopy("kill", m, m.firm_name)}
        onConfirm={() =>
          update.mutate({ path: { mapping_id: m.id }, body: confirmBody("kill", m) })
        }
      />
    </label>
  );
}

/** The mapping's effective rules, routing and cadence, in words for the diagram. */
function atFirm(r: MappingResolved): AtFirm {
  return {
    rules: r.policies.map((p) => {
      const applied = p.sources.find((s) => s.applies);
      return applied && Object.keys(applied.params).length
        ? `${p.display_name}: ${paramsText(applied)}`
        : p.display_name;
    }),
    alerts: r.alert_routing.map(
      (route) =>
        `${route.urgency} to ${route.channels.length ? channels(route.channels) : "nowhere"}`,
    ),
    cadence:
      r.cadence.override_min_wait_hours !== null
        ? `at least ${hours(r.cadence.min_wait_hours)} between contacts at this firm`
        : undefined,
  };
}

function Overview({
  mapping: m,
  versionId,
  diagram,
}: {
  mapping: MappingOut;
  versionId: string;
  diagram: ReactNode;
}) {
  const connections = useQuery(listConnectionsOptions({ path: { firm_id: m.firm_id } }));
  const checklist = useChecklist(m.firm_id, versionId, m.identities);
  const labels = new Map((connections.data ?? []).map((c) => [c.id, c.label]));
  return (
    <div className="grid gap-8 lg:min-h-0 lg:flex-1 lg:grid-cols-2 lg:gap-0">
      <div className="space-y-8 lg:overflow-y-auto lg:border-r lg:pr-8 lg:pb-8">
        <dl className="divide-y text-sm">
          <Row label="Agent">
            <Link
              to="/agents/$handle"
              params={{ handle: m.agent_handle }}
              search={{ tab: "overview", v: m.version }}
              className="font-mono underline"
            >
              @{m.agent_handle} v{m.version}
            </Link>
          </Row>
          <Row label="Traffic share">{m.ab_weight}%</Row>
          <Row label="Mapped">{dateTime(m.mapped_at)}</Row>
        </dl>
        <Section title="Connections">
          <ul className="divide-y text-sm">
            {(checklist.data ?? []).map((item) => (
              <li key={item.connector} className="flex items-center gap-3 py-2.5">
                <ConnectorIcon connector={item.connector} />
                <span className="w-32">{CONNECTOR_NAMES[item.connector] ?? item.connector}</span>
                <span className="flex-1">
                  {item.connection_id ? (labels.get(item.connection_id) ?? "Bound") : "Not bound"}
                </span>
                <span className={item.ok ? "text-success" : "text-brass"}>{item.reason}</span>
              </li>
            ))}
          </ul>
          {checklist.isPending && <Skeleton className="h-10 w-full" />}
        </Section>
      </div>
      {/* The same dotted canvas as the agent overview, with this firm's settings applied. */}
      <aside className="rounded-xl border bg-[radial-gradient(var(--color-border)_1px,transparent_1px)] [background-size:18px_18px] p-6 lg:ml-8 lg:h-full lg:overflow-y-auto">
        <Section
          title="How it works here"
          hint="The agent version, with this firm's rules, routing and cadence."
        >
          {diagram}
        </Section>
      </aside>
    </div>
  );
}

/** Policy rules with where each setting comes from, then the firm's routing, cadence and hours. */
function Guardrails({ resolved: r }: { resolved: MappingResolved }) {
  return (
    <div className="max-w-3xl space-y-8">
      <Section
        title="Policy rules"
        hint="The agent version's pack plus the firm's floor. A mapping override replaces them only by being stricter."
      >
        {r.policies.length ? (
          <ul className="divide-y">
            {r.policies.map((p) => (
              <PolicyRow key={p.rule} policy={p} />
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">No policy rules apply to this agent here.</p>
        )}
      </Section>
      <Section title="Follow-up cadence">
        <p className="text-sm">{cadenceText(r.cadence)}</p>
      </Section>
      <Section
        title="Alert routing"
        hint="This mapping wins, then the firm, then the agent version."
      >
        <ul className="divide-y text-sm">
          {r.alert_routing.map((route) => (
            <li key={route.urgency} className="grid grid-cols-[3rem_1fr] gap-3 py-2.5">
              <span className="font-medium">{route.urgency}</span>
              <div>
                <p>
                  {route.channels.length ? channels(route.channels) : "Nowhere"}
                  {route.source && (
                    <span className="text-muted-foreground">
                      {" "}
                      · from {SOURCE_LABEL[route.source].toLowerCase()}
                    </span>
                  )}
                </p>
                <p className="text-muted-foreground text-xs">
                  {(["mapping", "firm", "version"] as const)
                    .filter((s) => s !== route.source && route[s]?.length)
                    .map((s) => `${SOURCE_LABEL[s]}: ${channels(route[s] ?? [])}`)
                    .join(" · ")}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Firm hours" hint={`In ${r.timezone}.`}>
        <dl className="divide-y text-sm">
          {DAYS.map(([day, name]) => {
            const w = r.business_hours[day];
            return (
              <Row key={day} label={name}>
                {w ? `${w.start}–${w.end}` : "Closed"}
              </Row>
            );
          })}
          <Row label="Quiet hours">
            {r.quiet_hours ? `${r.quiet_hours.start}–${r.quiet_hours.end}` : "None"}
          </Row>
        </dl>
      </Section>
    </div>
  );
}

function PolicyRow({ policy: p }: { policy: ResolvedPolicy }) {
  return (
    <li className="py-3">
      <p className="text-sm font-medium">
        {p.display_name}
        {p.required && (
          <span className="text-muted-foreground font-normal"> · required by the platform</span>
        )}
      </p>
      <p className="text-muted-foreground text-sm">{p.description}</p>
      <ul className="mt-1.5 space-y-0.5 text-xs">
        {p.sources.map((s) => (
          <li
            key={s.source}
            className={s.applies ? undefined : "text-muted-foreground line-through"}
          >
            <span className="text-muted-foreground inline-block w-36 no-underline">
              {SOURCE_LABEL[s.source]}
            </span>
            <span className="font-mono">{paramsText(s)}</span>
          </li>
        ))}
      </ul>
    </li>
  );
}

function History({ mapping: m, resolved: r }: { mapping: MappingOut; resolved: MappingResolved }) {
  if (!r.history.length)
    return (
      <p className="text-muted-foreground text-sm">
        This is the first mapping of @{m.agent_handle} here.
      </p>
    );
  return (
    <Section
      title="Earlier versions at this firm"
      hint="Each switch keeps the previous mapping, turned off."
    >
      <ul className="divide-y text-sm">
        {r.history.map((h) => (
          <li key={h.id} className="flex items-center gap-3 py-2.5">
            <Link
              to="/firm-mappings/$mappingId"
              params={{ mappingId: h.id }}
              search={{ tab: "overview" }}
              className="font-mono underline"
            >
              v{h.version}
            </Link>
            <StatusBadge status={h.status} />
            <span className="text-muted-foreground">mapped {relativeTime(h.mapped_at)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function cadenceText(c: MappingResolved["cadence"]): string {
  if (c.override_min_wait_hours !== null)
    return `At least ${hours(c.min_wait_hours)} between contacts, set by this mapping (the agent version's minimum is ${hours(c.version_min_wait_hours)}).`;
  return c.min_wait_hours
    ? `At least ${hours(c.min_wait_hours)} between contacts, as the agent version sets it.`
    : "No minimum wait: the agent version doesn't follow up.";
}

const channels = (list: string[]) => list.map((c) => CHANNEL_LABEL[c] ?? c).join(", ");

/** `{n: 3, window: "week"}` → "Limit 3 · Window week"; no params → "On". */
function paramsText({ params }: PolicySource): string {
  const parts = Object.entries(params).map(
    ([k, v]) => `${label(k)} ${Array.isArray(v) ? v.join(", ") : String(v)}`,
  );
  return parts.length ? parts.join(" · ") : "On";
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-sm font-semibold">{title}</h2>
      {hint && <p className="text-muted-foreground mb-2 text-sm">{hint}</p>}
      {children}
    </section>
  );
}

function Row({ label: name, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-3 py-2.5">
      <dt className="text-muted-foreground">{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}
