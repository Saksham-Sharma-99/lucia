import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  enableConnectionInboundMutation,
  testConnectionMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectionOut, RegistryEntryOut, TestResult } from "@/api/generated/types.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CopyField } from "@/components/shared/copy-field";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { relativeTime } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

import { SETUP, TEST_TARGET, type SetupConnector } from "../model";

type Run = (tool?: string, input?: Record<string, string>) => void;

/** Sign-in check, then one row per tool: outbound tools send for real, inbound tools wait for an event. */
export function TestsPanel({
  connection: c,
  tools,
}: {
  connection: ConnectionOut;
  tools: RegistryEntryOut[];
}) {
  const test = useApiMutation(
    {
      ...testConnectionMutation(),
      // A failed test is a result to show, not an error.
      onSuccess: (r, vars) => {
        const message = `${vars.body.tool ?? "Sign-in check"}: ${r.detail}`;
        if (r.ok) toast.success(message);
        else toast.error(message);
      },
    },
    { stale: STALE.connection, error: "Test didn't run" },
  );
  const run: Run = (tool, input) =>
    test.mutate({ path: { conn_id: c.id }, body: tool ? { tool, input } : {} });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm font-medium">Tests</p>
        <Button size="sm" variant="outline" disabled={test.isPending} onClick={() => run()}>
          Check sign-in
        </Button>
        <ResultPill result={c.test_results.auth} />
      </div>
      <ul className="divide-border divide-y rounded-lg border">
        {tools
          .filter((t) => t.available)
          .map((t) => (
            <li key={t.name} className="px-4 py-3">
              {t.direction === "outbound" ? (
                <OutboundTest connection={c} tool={t} running={test.isPending} run={run} />
              ) : (
                <InboundTest connection={c} tool={t} running={test.isPending} run={run} />
              )}
            </li>
          ))}
      </ul>
      {c.webhook_url && (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">Webhook for inbound events</p>
          <CopyField value={c.webhook_url} />
        </div>
      )}
    </div>
  );
}

function OutboundTest({
  connection: c,
  tool,
  running,
  run,
}: {
  connection: ConnectionOut;
  tool: RegistryEntryOut;
  running: boolean;
  run: Run;
}) {
  const [value, setValue] = useState("");
  const [confirming, setConfirming] = useState(false);
  const key = ((tool.params_schema as { required?: string[] }).required ?? [])[0];
  const target = key ? TEST_TARGET[key] : undefined;
  const to = value.trim();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="w-44 text-sm">{tool.display_name}</span>
      <ResultPill result={c.test_results[tool.name]} />
      {target && (
        <Input
          aria-label={target.label}
          className="w-64"
          value={value}
          placeholder={target.placeholder}
          onChange={(e) => setValue(e.target.value)}
        />
      )}
      <Button
        size="sm"
        variant="outline"
        className="ml-auto"
        disabled={running || (!!target && !to)}
        onClick={() => setConfirming(true)}
      >
        Send test
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Send a real test?"
        description={
          target
            ? `This sends a real ${tool.display_name.toLowerCase()} to ${to} from ${c.label}.`
            : `This runs ${tool.display_name.toLowerCase()} for real from ${c.label}.`
        }
        confirmLabel="Send test"
        // Send only an input the builder could see and fill in.
        onConfirm={() => run(tool.name, key && target ? { [key]: to } : {})}
      />
    </div>
  );
}

function InboundTest({
  connection: c,
  tool,
  running,
  run,
}: {
  connection: ConnectionOut;
  tool: RegistryEntryOut;
  running: boolean;
  run: Run;
}) {
  const enable = useApiMutation(enableConnectionInboundMutation(), {
    stale: STALE.connection,
    success: (r) => r.detail,
    error: "Couldn't enable inbound",
  });
  // Gmail only pushes events once Lucia has asked it to watch the mailbox.
  const needsWatch = c.connector === "gmail" && !c.config.watch_expiration;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <span className="w-44 text-sm">{tool.display_name}</span>
        <ResultPill result={c.test_results[tool.name]} />
        <span className="text-muted-foreground text-xs">
          {c.last_inbound_at
            ? `Last event: ${c.last_inbound_type} · ${relativeTime(c.last_inbound_at)}`
            : "No events yet"}
        </span>
        {needsWatch ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={enable.isPending}
            onClick={() => enable.mutate({ path: { conn_id: c.id } })}
          >
            Enable inbound
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            disabled={running}
            onClick={() => run(tool.name)}
          >
            <RefreshCwIcon /> Recheck
          </Button>
        )}
      </div>
      <p className="text-muted-foreground text-xs">
        {SETUP[c.connector as SetupConnector]?.inboundAsk(c)}
      </p>
    </div>
  );
}

function ResultPill({ result }: { result?: TestResult }) {
  if (!result) return <StatusBadge status="never" />;
  return (
    <span title={result.detail} className="flex items-center gap-2">
      <StatusBadge status={result.ok ? "pass" : "fail"} />
      <span className="text-muted-foreground text-xs">{relativeTime(result.at)}</span>
    </span>
  );
}
