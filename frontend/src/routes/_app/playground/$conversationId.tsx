import { createFileRoute } from "@tanstack/react-router";

import { Playground } from "@/features/playground/playground";

import { playgroundSearch } from "@/features/playground/search";

export const Route = createFileRoute("/_app/playground/$conversationId")({
  staticData: { fullBleed: true },
  validateSearch: playgroundSearch,
  component: function Chat() {
    const { conversationId } = Route.useParams();
    const search = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <Playground
        conversationId={conversationId}
        search={search}
        onSearch={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch }) })}
        onOpen={(id, firm) =>
          void (id
            ? navigate({
                to: "/playground/$conversationId",
                params: { conversationId: id },
                search: { firm },
              })
            : navigate({ to: "/playground", search: { firm } }))
        }
      />
    );
  },
});
