import { useState } from "react";

import { updateConnectionMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { ConnectionOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

/** Stored secrets, shown only as hints (••••a1f3). Replacing one never reveals the old value. */
export function SecretsSection({ connection: c }: { connection: ConnectionOut }) {
  const [replacing, setReplacing] = useState<string | null>(null);
  const hints = Object.entries(c.secret_hints);
  if (!hints.length) return null;
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Secrets</p>
      <ul className="space-y-1.5 text-sm">
        {hints.map(([key, hint]) => (
          <li key={key} className="flex flex-wrap items-center gap-3">
            <span className="text-muted-foreground w-36">{key.replaceAll("_", " ")}</span>
            <code className="font-mono text-xs">{hint}</code>
            {replacing === key ? (
              <ReplaceSecret connectionId={c.id} name={key} onDone={() => setReplacing(null)} />
            ) : (
              <Button size="sm" variant="ghost" onClick={() => setReplacing(key)}>
                Replace
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReplaceSecret({
  connectionId,
  name,
  onDone,
}: {
  connectionId: string;
  name: string;
  onDone: () => void;
}) {
  const [value, setValue] = useState("");
  const update = useApiMutation(
    { ...updateConnectionMutation(), onSuccess: onDone },
    { stale: STALE.connection, success: "Secret replaced" },
  );
  return (
    <>
      <Input
        type="password"
        className="w-56"
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label={`New ${name}`}
      />
      <Button
        size="sm"
        disabled={!value || update.isPending}
        onClick={() =>
          update.mutate({ path: { conn_id: connectionId }, body: { secrets: { [name]: value } } })
        }
      >
        Save
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Cancel
      </Button>
    </>
  );
}
