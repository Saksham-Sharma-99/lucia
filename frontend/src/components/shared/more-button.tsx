import { MoreHorizontalIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { Button } from "@/components/ui/button";

/** The "⋯" button that opens an actions menu. */
export function MoreButton({ label, ...props }: { label: string } & ComponentProps<typeof Button>) {
  return (
    <Button variant="ghost" size="icon-sm" aria-label={label} {...props}>
      <MoreHorizontalIcon />
    </Button>
  );
}
