import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { RunsList } from "@/features/runs/runs-list";

export const Route = createFileRoute("/_app/runs/")({
  validateSearch: z.object({
    firm: z.string().optional().catch(undefined),
    agent: z.string().optional().catch(undefined),
    status: z
      .enum([
        "CREATED",
        "ACTIVE",
        "TAKEN_OVER",
        "PAUSED",
        "AWAITING_CONFIRMATION",
        "COMPLETED",
        "ENDED",
        "FAILED",
      ])
      .optional()
      .catch(undefined),
    q: z.string().optional().catch(undefined),
    page: z.number().int().min(1).catch(1).default(1),
  }),
  component: function Runs() {
    const search = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <RunsList
        search={search}
        onSearch={(patch) =>
          void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
        }
      />
    );
  },
});
