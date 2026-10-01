import { hueFor, initials } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Initials on a colour derived from a stable key (agent handle, firm colour). */
export function Avatar({
  label,
  colorKey,
  color,
  size = "md",
}: {
  label: string;
  colorKey?: string;
  color?: string;
  size?: "sm" | "md" | "lg";
}) {
  const background = color ?? `oklch(0.62 0.11 ${hueFor(colorKey ?? label)})`;
  return (
    <span
      aria-hidden
      style={{ background }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md font-semibold text-white",
        size === "sm" && "size-6 text-[0.625rem]",
        size === "md" && "size-8 text-xs",
        size === "lg" && "size-11 text-sm",
      )}
    >
      {initials(label)}
    </span>
  );
}
