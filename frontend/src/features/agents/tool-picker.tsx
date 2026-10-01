import { ArrowDownLeftIcon, ArrowUpRightIcon } from "lucide-react";

import type { Capability, ConnectorOut } from "@/api/generated/types.gen";
import { ConnectorIcon } from "@/components/shared/connector-icon";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

const RISK: Record<string, string> = {
  read: "reads",
  internal_write: "writes internally",
  external_comm: "contacts people",
};

/**
 * Connectors with their tools. Checking a connector turns on all its tools; tools can then be
 * narrowed. In read-only mode only the selected connectors are shown.
 */
export function ToolPicker({
  connectors,
  value,
  onChange,
  readOnly,
}: {
  connectors: ConnectorOut[];
  value: Capability[];
  onChange?: (value: Capability[]) => void;
  readOnly?: boolean;
}) {
  const picked = new Map(value.map((c) => [c.connector, new Set(c.tools)]));
  const emit = (next: Map<string, Set<string>>) =>
    onChange?.(
      connectors
        .filter((c) => next.get(c.name)?.size)
        .map((c) => ({
          connector: c.name,
          tools: c.tools.map((t) => t.name).filter((t) => next.get(c.name)?.has(t)),
        })),
    );

  const shown = readOnly ? connectors.filter((c) => picked.has(c.name)) : connectors;
  return (
    <div className="grid gap-3">
      {shown.map((c) => {
        const tools = picked.get(c.name);
        const on = !!tools?.size;
        return (
          <div
            key={c.name}
            className={cn(
              "rounded-lg border px-4 py-3 transition-colors",
              on ? "border-brass/50 bg-brass/[0.04]" : "border-border",
              !c.available && "opacity-60",
            )}
          >
            <label className="flex items-start gap-3">
              {!readOnly && (
                <Checkbox
                  className="mt-1.5"
                  checked={on}
                  disabled={!c.available && !on}
                  onCheckedChange={(checked) => {
                    const next = new Map(picked);
                    if (checked) next.set(c.name, new Set(c.tools.map((t) => t.name)));
                    else next.delete(c.name);
                    emit(next);
                  }}
                />
              )}
              <ConnectorIcon connector={c.name} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{c.display_name}</span>
                <span className="text-muted-foreground block text-sm">
                  {c.available ? c.description : "Not available yet"}
                </span>
              </span>
            </label>
            {on && (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {c.tools
                  .filter((t) => !readOnly || tools.has(t.name))
                  .map((t) => (
                    <li key={t.name}>
                      <label className="flex items-start gap-2.5 text-sm">
                        {!readOnly && (
                          <Checkbox
                            className="mt-0.5"
                            checked={tools.has(t.name)}
                            onCheckedChange={(checked) => {
                              const set = new Set(tools);
                              if (checked) set.add(t.name);
                              else set.delete(t.name);
                              emit(new Map(picked).set(c.name, set));
                            }}
                          />
                        )}
                        {t.direction === "inbound" ? (
                          <ArrowDownLeftIcon
                            className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
                            aria-label="Inbound"
                          />
                        ) : (
                          <ArrowUpRightIcon
                            className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
                            aria-label="Outbound"
                          />
                        )}
                        <span>
                          {t.display_name}
                          <span
                            className={cn(
                              "ml-2 text-xs",
                              t.risk_tier === "external_comm"
                                ? "text-brass"
                                : "text-muted-foreground",
                            )}
                          >
                            {RISK[t.risk_tier ?? ""] ?? t.risk_tier}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        );
      })}
      {!readOnly && (
        <p className="text-muted-foreground text-sm">
          Credentials are set per firm, in Firms → Connections.
        </p>
      )}
    </div>
  );
}
