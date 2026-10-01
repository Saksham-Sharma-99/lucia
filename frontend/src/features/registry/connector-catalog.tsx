import { useState } from "react";

import type { ConnectorOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { EmptyState } from "@/components/shared/empty-state";
import { QuickFilters } from "@/components/shared/quick-filters";
import { StatCards } from "@/components/shared/stat-cards";
import { StatusBadge } from "@/components/shared/status-badge";
import { Input } from "@/components/ui/input";
import { CONNECTOR_KIND } from "@/lib/connectors";
import { cn } from "@/lib/utils";

import { ConnectorDrawer } from "./connector-drawer";
import { connectorState, matches, type ConnectorState } from "./model";
import type { Registry } from "./use-registry";

type Filter = "all" | ConnectorState;

/** The connector catalog as cards; clicking one opens its details in a drawer. */
export function ConnectorCatalog({
  registry,
  open,
  onOpen,
}: {
  registry: Registry;
  /** The connector shown in the drawer, from the URL. */
  open?: string;
  onOpen: (name: string | undefined) => void;
}) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const withState = registry.connectors.map((c) => ({
    connector: c,
    state: connectorState(c, registry.platform),
  }));
  const count = (s: ConnectorState) => withState.filter((x) => x.state === s).length;
  const shown = withState.filter(
    (x) =>
      (filter === "all" || x.state === filter) &&
      matches(q, x.connector.display_name, x.connector.description, x.connector.name),
  );
  const selected = withState.find((x) => x.connector.name === open);

  return (
    <>
      <StatCards
        stats={[
          { label: "Ready", value: count("ready") },
          { label: "Needs setup", value: count("needs setup") },
          { label: "Coming soon", value: count("coming soon") },
          { label: "Tools", value: registry.tools.length },
        ]}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input
          aria-label="Search connectors"
          className="w-72"
          placeholder="Search connectors"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <QuickFilters
          label="Show"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All", count: withState.length },
            { value: "ready", label: "Ready", count: count("ready") },
            { value: "needs setup", label: "Needs setup", count: count("needs setup") },
            { value: "coming soon", label: "Coming soon", count: count("coming soon") },
          ]}
        />
      </div>
      {shown.length ? (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map(({ connector, state }) => (
            <ConnectorCard
              key={connector.name}
              connector={connector}
              state={state}
              onOpen={() => onOpen(connector.name)}
            />
          ))}
        </ul>
      ) : (
        <EmptyState title="No connectors match" description="Try a different search or filter." />
      )}
      {selected && (
        <ConnectorDrawer
          connector={selected.connector}
          state={selected.state}
          registry={registry}
          onClose={() => onOpen(undefined)}
        />
      )}
    </>
  );
}

function ConnectorCard({
  connector: c,
  state,
  onOpen,
}: {
  connector: ConnectorOut;
  state: ConnectorState;
  onOpen: () => void;
}) {
  const tools = c.tools.length;
  return (
    <li
      className={cn(
        "bg-card hover:border-brass/60 relative flex flex-col gap-3 rounded-xl border p-4 transition-colors",
        state === "coming soon" && "border-dashed",
      )}
    >
      <div className="flex items-start gap-3">
        <ConnectorIcon connector={c.name} />
        <div className="min-w-0 flex-1">
          {/* A stretched button: the whole card opens the drawer. */}
          <button
            type="button"
            onClick={onOpen}
            className="block truncate text-left font-semibold after:absolute after:inset-0 after:rounded-xl"
          >
            {c.display_name}
          </button>
          <p className="text-muted-foreground text-xs font-medium tracking-wider uppercase">
            {CONNECTOR_KIND[c.name] ?? c.name}
          </p>
        </div>
        <StatusBadge status={state} />
      </div>
      <p className="text-muted-foreground line-clamp-2 text-sm">{c.description}</p>
      <p className="text-muted-foreground mt-auto font-mono text-xs">
        {state === "coming soon"
          ? "Not available yet"
          : `${tools} ${tools === 1 ? "tool" : "tools"}`}
      </p>
    </li>
  );
}
