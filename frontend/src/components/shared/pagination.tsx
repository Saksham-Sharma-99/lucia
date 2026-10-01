import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

export function Pagination({
  page,
  limit,
  total,
  onPage,
}: {
  page: number;
  limit: number;
  total: number;
  onPage: (page: number) => void;
}) {
  if (total === 0) return null;
  const first = (page - 1) * limit + 1;
  const last = Math.min(page * limit, total);
  // Everything fits on one page: say how many, without arrows that look clickable but aren't.
  if (page === 1 && total <= limit)
    return <p className="text-muted-foreground mt-3 text-sm">{total} in total</p>;
  if (first > total)
    return (
      <div className="text-muted-foreground mt-3 flex items-center gap-3 text-sm">
        Page {page} is past the end of the {total} results.
        <Button variant="outline" size="sm" onClick={() => onPage(1)}>
          Go to the first page
        </Button>
      </div>
    );
  return (
    <div className="text-muted-foreground mt-3 flex items-center justify-between text-sm">
      <span>
        {first}–{last} of {total}
      </span>
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeftIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Next page"
          disabled={last >= total}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRightIcon />
        </Button>
      </div>
    </div>
  );
}
