import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { AgentsList } from "@/features/agents/agents-list";

export const Route = createFileRoute("/_app/agents/")({
  validateSearch: z.object({
    q: z.string().optional().catch(undefined),
    status: z.enum(["active", "archived"]).optional().catch(undefined),
    templates: z.boolean().optional().catch(undefined),
    page: z.number().int().min(1).catch(1).default(1),
  }),
  component: function Agents() {
    const search = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <AgentsList
        search={search}
        onSearch={(patch) =>
          void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
        }
      />
    );
  },
});
