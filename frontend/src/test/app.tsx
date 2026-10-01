import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { routeTree } from "@/routeTree.gen";

/** Render the real app (routes, guards, providers) at `url`, against the MSW API. */
export async function renderApp(url: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [url] }),
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await router.load();
  return { ...view, router, queryClient, user: userEvent.setup() };
}

export const path = (router: { state: { location: { pathname: string } } }) =>
  router.state.location.pathname;
export const search = (router: { state: { location: { search: unknown } } }) =>
  router.state.location.search as Record<string, unknown>;
type App = { user: ReturnType<typeof userEvent.setup> };

/** Open an actions menu by its button's name and wait for its first item. */
export async function openMenu(app: App, menu: string) {
  await app.user.click(await screen.findByRole("button", { name: menu }));
  await screen.findAllByRole("menuitem");
}

/** Open a menu and pick an item, e.g. choose(app, "Actions for @records", "Archive"). */
export async function choose(app: App, menu: string, item: string | RegExp) {
  await openMenu(app, menu);
  await app.user.click(screen.getByRole("menuitem", { name: item }));
}

export { screen };
