import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { RegistryPage } from "@/features/registry/registry-page";

export const Route = createFileRoute("/_app/registry")({
  validateSearch: z.object({
    // The connector open in the drawer, so it can be linked to.
    connector: z.string().optional().catch(undefined),
  }),
  component: function Registry() {
    const { connector } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <RegistryPage
        connector={connector}
        onConnector={(c) => void navigate({ search: { connector: c }, replace: true })}
      />
    );
  },
});
