import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="border-border flex flex-col items-start gap-2 rounded-lg border border-dashed px-6 py-10">
      <p className="font-medium">{title}</p>
      {description && <p className="text-muted-foreground max-w-prose text-sm">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
