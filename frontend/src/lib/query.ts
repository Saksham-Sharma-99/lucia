/** What QueryState needs from a TanStack query (or a combined, query-shaped result). */
export type QueryLike<T> = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
};

/**
 * Several queries as one: data once all have data, the first error otherwise. `refetch` retries
 * only the failed queries; the others are fine or already loading.
 */
export function allOf<Q extends Record<string, QueryLike<unknown>>>(
  queries: Q,
): QueryLike<{ [K in keyof Q]: NonNullable<Q[K]["data"]> }> {
  const list = Object.values(queries);
  const ready = list.every((q) => q.data !== undefined);
  return {
    isPending: list.some((q) => q.isPending),
    isError: list.some((q) => q.isError),
    error: list.find((q) => q.isError)?.error ?? null,
    data: ready
      ? (Object.fromEntries(Object.entries(queries).map(([k, q]) => [k, q.data])) as {
          [K in keyof Q]: NonNullable<Q[K]["data"]>;
        })
      : undefined,
    refetch: () => Promise.all(list.filter((q) => q.isError).map((q) => q.refetch())),
  };
}
