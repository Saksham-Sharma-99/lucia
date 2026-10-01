import { createFileRoute, redirect } from "@tanstack/react-router";

import { getMeOptions } from "@/api/generated/@tanstack/react-query.gen";
import { AppShell } from "@/features/shell/app-shell";
import { isProblem } from "@/lib/problem";

/** Every signed-in page lives under this layout; a missing session sends you to /login. */
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    try {
      const user = await context.queryClient.ensureQueryData(getMeOptions());
      return { user };
    } catch (error) {
      if (isProblem(error) && error.status === 401) {
        throw redirect({ to: "/login", search: { redirect: location.href } });
      }
      throw error;
    }
  },
  component: function App() {
    const { user } = Route.useRouteContext();
    return <AppShell user={user} />;
  },
});
