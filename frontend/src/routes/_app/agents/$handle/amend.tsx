import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { AmendPage } from "@/features/agents/amend";

export const Route = createFileRoute("/_app/agents/$handle/amend")({
  validateSearch: z.object({ from: z.number().int().min(1).catch(1).default(1) }),
  component: function Amend() {
    const { handle } = Route.useParams();
    const { from } = Route.useSearch();
    return <AmendPage key={`${handle}-${from}`} handle={handle} from={from} />;
  },
});
