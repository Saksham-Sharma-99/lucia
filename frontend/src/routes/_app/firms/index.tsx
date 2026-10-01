import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { FirmsList } from "@/features/firms/firms-list";

export const Route = createFileRoute("/_app/firms/")({
  validateSearch: z.object({
    q: z.string().optional().catch(undefined),
    page: z.number().int().min(1).catch(1).default(1),
  }),
  component: function Firms() {
    const { q, page } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <FirmsList
        q={q}
        page={page}
        onSearch={(patch) =>
          void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
        }
      />
    );
  },
});
