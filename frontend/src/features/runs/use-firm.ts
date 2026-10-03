import { useQuery } from "@tanstack/react-query";

import { listFirmsOptions } from "@/api/generated/@tanstack/react-query.gen";

export const FIRM_KEY = "lucia.firm";

function remembered(): string | null {
  try {
    return localStorage.getItem(FIRM_KEY);
  } catch {
    return null; // private mode or blocked storage: no memory, still works
  }
}

/**
 * The firm the playground and runs pages work in: the URL's `firm` wins, then the last one
 * used (if it still exists and is active), then the first active firm.
 */
export function useFirm(fromUrl?: string) {
  const firms = useQuery(listFirmsOptions({ query: { status: "active", limit: 100 } }));
  const items = firms.data?.items ?? [];
  const known = (id: string | null | undefined) => !!id && items.some((f) => f.id === id);
  const firmId = fromUrl ?? (known(remembered()) ? remembered()! : (items[0]?.id ?? undefined));
  const setFirm = (id: string) => {
    try {
      localStorage.setItem(FIRM_KEY, id);
    } catch {
      // storage unavailable: the URL still carries the choice
    }
  };
  return { firmId, firms, setFirm };
}
