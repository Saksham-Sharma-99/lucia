import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { MappingsPage } from "@/features/mappings/mappings-page";

export const Route = createFileRoute("/_app/firm-mappings/")({
  validateSearch: z.object({
    firm: z.string().optional().catch(undefined),
    page: z.number().int().min(1).catch(1).default(1),
  }),
  component: function FirmMappings() {
    const { firm, page } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <MappingsPage
        firm={firm}
        page={page}
        onFirm={(id) => void navigate({ search: { firm: id, page: 1 }, replace: true })}
        onPage={(n) => void navigate({ search: (prev) => ({ ...prev, page: n }), replace: true })}
      />
    );
  },
});
