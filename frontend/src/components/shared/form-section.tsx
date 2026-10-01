import type { ReactNode } from "react";

/** A titled block of a form; sections are separated by rules, not boxed in cards. */
export function FormSection({
  title,
  description,
  children,
  aside,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="border-border grid gap-4 border-t py-6 first:border-t-0 first:pt-0 md:grid-cols-[14rem_1fr]">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
        {aside}
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  );
}
