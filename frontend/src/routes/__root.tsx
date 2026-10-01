import type { QueryClient } from "@tanstack/react-query";
import { Link, Outlet, createRootRouteWithContext } from "@tanstack/react-router";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="bg-background text-foreground min-h-screen">
      <header className="flex items-center gap-6 border-b px-6 py-3">
        <span className="font-semibold">Lucia Studio</span>
        <nav className="text-muted-foreground flex gap-4 text-sm">
          <Link to="/" className="[&.active]:text-foreground">
            Home
          </Link>
          <Link to="/agents" className="[&.active]:text-foreground">
            Agents
          </Link>
        </nav>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  );
}
