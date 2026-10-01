import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { problemMessage } from "@/lib/problem";
import type { QueryLike } from "@/lib/query";

import { EmptyState } from "./empty-state";
import { TableSkeleton } from "./loading";

/**
 * The loading, error and empty states every list and page needs, so callers only render data.
 * A failed background refetch keeps showing the data it already has, with a quiet note.
 */
export function QueryState<T>({
  query,
  what,
  isEmpty,
  empty,
  loading = <TableSkeleton />,
  children,
}: {
  query: QueryLike<T>;
  /** Named in the error message: "Agents didn't load". */
  what: string;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  loading?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  const retry = <Button onClick={() => void query.refetch()}>Try again</Button>;
  if (query.data === undefined) {
    if (query.isError)
      return (
        <EmptyState
          title={`${what} didn't load`}
          description={problemMessage(query.error)}
          action={retry}
        />
      );
    return loading;
  }
  return (
    <>
      {query.isError && (
        <p role="status" className="text-brass mb-3 text-sm">
          Couldn't refresh: {problemMessage(query.error)}. Showing the last loaded data.
        </p>
      )}
      {isEmpty?.(query.data) ? empty : children(query.data)}
    </>
  );
}
