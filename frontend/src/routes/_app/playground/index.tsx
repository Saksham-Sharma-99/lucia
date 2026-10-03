import { createFileRoute } from "@tanstack/react-router";

import { Playground } from "@/features/playground/playground";

import { playgroundSearch } from "@/features/playground/search";

export const Route = createFileRoute("/_app/playground/")({
  staticData: { fullBleed: true },
  validateSearch: playgroundSearch,
  component: function NewChat() {
    const search = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <Playground
        search={search}
        onSearch={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch }) })}
        onOpen={(id, firm) =>
          void (id
            ? navigate({
                to: "/playground/$conversationId",
                params: { conversationId: id },
                search: { firm },
              })
            : navigate({ search: { firm } }))
        }
      />
    );
  },
});
