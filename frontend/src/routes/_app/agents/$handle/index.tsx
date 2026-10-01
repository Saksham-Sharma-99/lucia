import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { AgentDetailPage } from "@/features/agents/agent-detail";
import { AGENT_TABS } from "@/features/agents/editor";

export const Route = createFileRoute("/_app/agents/$handle/")({
  validateSearch: z.object({
    tab: z.enum(AGENT_TABS).catch("overview").default("overview"),
    v: z.number().int().min(1).optional().catch(undefined),
  }),
  component: function AgentRoute() {
    const { handle } = Route.useParams();
    const { tab, v } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <AgentDetailPage
        key={handle}
        handle={handle}
        tab={tab}
        v={v}
        onChange={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch }) })}
      />
    );
  },
});
