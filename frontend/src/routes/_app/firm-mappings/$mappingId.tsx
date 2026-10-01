import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { MappingDetailPage } from "@/features/mappings/mapping-detail";
import { MAPPING_TABS } from "@/features/mappings/model";

export const Route = createFileRoute("/_app/firm-mappings/$mappingId")({
  validateSearch: z.object({
    tab: z.enum(MAPPING_TABS).catch("overview").default("overview"),
  }),
  component: function MappingDetail() {
    const { mappingId } = Route.useParams();
    const { tab } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <MappingDetailPage
        key={mappingId}
        mappingId={mappingId}
        tab={tab}
        onTab={(t) => void navigate({ search: { tab: t }, replace: true })}
      />
    );
  },
});
