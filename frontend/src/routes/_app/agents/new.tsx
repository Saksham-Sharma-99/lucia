import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { NewAgent } from "@/features/agents/new-agent";

export const Route = createFileRoute("/_app/agents/new")({
  validateSearch: z.object({ template: z.string().optional().catch(undefined) }),
  component: function New() {
    const { template } = Route.useSearch();
    return <NewAgent key={template ?? "blank"} template={template} />;
  },
});
