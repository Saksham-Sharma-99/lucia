import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { FirmDetailPage } from "@/features/firms/firm-detail";
import { FIRM_TABS } from "@/features/firms/model";

export const Route = createFileRoute("/_app/firms/$firmId")({
  validateSearch: z.object({
    tab: z.enum(FIRM_TABS).catch("overview").default("overview"),
    // Set by the OAuth callback redirect after a consent link is approved.
    connected: z.string().optional().catch(undefined),
  }),
  component: function Firm() {
    const { firmId } = Route.useParams();
    const { tab, connected } = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <FirmDetailPage
        key={firmId}
        firmId={firmId}
        tab={tab}
        connected={connected}
        onTab={(t) => void navigate({ search: { tab: t }, replace: true })}
        onConnectedSeen={() => void navigate({ search: { tab }, replace: true })}
      />
    );
  },
});
