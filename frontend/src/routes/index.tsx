import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { getHealthOptions } from "@/api/generated/@tanstack/react-query.gen";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  const health = useQuery(getHealthOptions());

  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">Lucia Studio</h1>
      <p className="text-muted-foreground">Build, test and publish long-running agents.</p>
      <p className="text-sm">
        API:{" "}
        {health.isPending
          ? "checking…"
          : health.isError
            ? "unreachable"
            : `${health.data.status} (postgres ${health.data.postgres}, redis ${health.data.redis})`}
      </p>
    </section>
  );
}
