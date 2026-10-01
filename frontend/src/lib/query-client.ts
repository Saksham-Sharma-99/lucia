import { QueryClient } from "@tanstack/react-query";

import { isProblem } from "@/lib/problem";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // 4xx answers will not change on retry; only retry network and server errors.
      retry: (count, error) => count < 1 && !(isProblem(error) && error.status < 500),
    },
  },
});
