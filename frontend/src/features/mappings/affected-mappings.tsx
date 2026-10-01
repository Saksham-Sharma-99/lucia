import type { ReactNode } from "react";

import type { MappingOut, PageMappingOut } from "@/api/generated/types.gen";
import type { QueryLike } from "@/lib/query";

/**
 * For a destructive confirm: what it turns off. It says "none" only when the lookup succeeded,
 * so a failed request never reads as "nothing affected".
 */
export function AffectedMappings({
  query,
  intro,
  none,
  name,
}: {
  query: QueryLike<PageMappingOut>;
  intro: string;
  none: string;
  name: (m: MappingOut) => string;
}): ReactNode {
  if (query.isError)
    return (
      <>
        Couldn't check which mappings this turns off.{" "}
        <button type="button" className="underline" onClick={() => void query.refetch()}>
          Try again
        </button>
      </>
    );
  if (!query.data) return "Checking which mappings this turns off…";
  const { items, total } = query.data;
  if (!items.length) return none;
  return (
    <>
      {intro}
      <ul className="mt-2 list-disc pl-5">
        {items.map((m) => (
          <li key={m.id}>{name(m)}</li>
        ))}
        {total > items.length && <li>and {total - items.length} more</li>}
      </ul>
    </>
  );
}
