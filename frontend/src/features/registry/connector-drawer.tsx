import { ArrowDownLeftIcon, ArrowUpRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { ConnectorOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { StatusBadge } from "@/components/shared/status-badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isSetupConnector } from "@/features/firms/model";

import { HOW_IT_CONNECTS, type ConnectorState } from "./model";
import type { Registry } from "./use-registry";

/** Everything about one connector: what agents can do with it, how it sends, how firms connect it. */
export function ConnectorDrawer({
  connector: c,
  state,
  registry,
  onClose,
}: {
  connector: ConnectorOut;
  state: ConnectorState;
  registry: Registry;
  onClose: () => void;
}) {
  const names = new Set(c.tools.map((t) => t.name));
  const channels = registry.channels.filter((ch) => ch.channel_tool && names.has(ch.channel_tool));
  const inbound = c.tools.filter((t) => t.direction === "inbound").length;
  return (
    <Sheet open onOpenChange={(open) => open || onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <div className="flex items-center gap-3 pr-8">
            <ConnectorIcon connector={c.name} />
            <SheetTitle className="text-lg">{c.display_name}</SheetTitle>
            <StatusBadge status={state} />
          </div>
          <SheetDescription>{c.description}</SheetDescription>
        </SheetHeader>
        <Tabs defaultValue="tools" className="px-4 pb-6">
          <TabsList className="mb-4 w-full">
            <TabsTrigger value="tools">Tools</TabsTrigger>
            <TabsTrigger value="channels">Channels</TabsTrigger>
            <TabsTrigger value="setup">Setup</TabsTrigger>
          </TabsList>
          <TabsContent value="tools">
            <Heading count={c.tools.length}>What agents can do</Heading>
            <ul className="divide-y">
              {c.tools.map((t) => (
                <li key={t.name} className="flex gap-3 py-3">
                  {t.direction === "inbound" ? (
                    <ArrowDownLeftIcon
                      aria-label="inbound"
                      className="text-muted-foreground mt-0.5 size-4"
                    />
                  ) : (
                    <ArrowUpRightIcon
                      aria-label="outbound"
                      className="text-muted-foreground mt-0.5 size-4"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{t.display_name}</p>
                    <p className="text-muted-foreground text-sm">{t.description}</p>
                    <p className="text-muted-foreground mt-1 font-mono text-xs">
                      {t.name}
                      {t.risk_tier && ` · ${t.risk_tier.replaceAll("_", " ")}`}
                      {t.is_async && " · runs in the background"}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </TabsContent>
          <TabsContent value="channels">
            <Heading count={channels.length}>Follow-up and alert channels</Heading>
            {channels.length ? (
              <ul className="divide-y">
                {channels.map((ch) => (
                  <li key={ch.name} className="py-3">
                    <p className="text-sm font-medium">{ch.display_name}</p>
                    <p className="text-muted-foreground font-mono text-xs">
                      sends with {ch.channel_tool}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-sm">
                No channel sends through this connector.
              </p>
            )}
          </TabsContent>
          <TabsContent value="setup">
            <dl className="divide-y text-sm">
              <Row label="How firms connect">{HOW_IT_CONNECTS[c.setup] ?? c.setup}</Row>
              {isSetupConnector(c.name) && (
                <Row label="Platform app">
                  {state === "needs setup"
                    ? "Not set up yet: add its credentials to the backend .env"
                    : "Set up"}
                </Row>
              )}
              <Row label="Tools">
                {c.tools.length - inbound} outbound · {inbound} inbound
              </Row>
              <Row label="Credentials">Stored per firm, encrypted, in Firms → Connections</Row>
            </dl>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function Heading({ count, children }: { count: number; children: ReactNode }) {
  return (
    <h3 className="text-muted-foreground mb-1 flex justify-between text-xs font-medium tracking-wider uppercase">
      {children}
      <span className="tabular-nums">{count}</span>
    </h3>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-3 py-3">
      <dt className="text-muted-foreground text-xs font-medium tracking-wider uppercase">
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}
