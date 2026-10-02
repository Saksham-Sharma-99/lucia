import type { QueryClient } from "@tanstack/react-query";
import { Link, Outlet, createRootRouteWithContext } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { problemMessage } from "@/lib/problem";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The page fills the screen instead of the centered content column (playground). */
    fullBleed?: boolean;
  }
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: () => (
    <TooltipProvider>
      <Outlet />
      <Toaster position="bottom-right" />
    </TooltipProvider>
  ),
  notFoundComponent: () => (
    <div className="mx-auto max-w-md px-6 py-24">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground mt-2 text-sm">This page doesn't exist or was moved.</p>
      <Button className="mt-6" nativeButton={false} render={<Link to="/agents" />}>
        Go to agents
      </Button>
    </div>
  ),
  errorComponent: ({ error, reset }) => (
    <div className="mx-auto max-w-md px-6 py-24">
      <h1 className="text-xl font-semibold">This page failed to load</h1>
      <p className="text-muted-foreground mt-2 text-sm">{problemMessage(error)}</p>
      <Button className="mt-6" onClick={reset}>
        Retry
      </Button>
    </div>
  ),
});
