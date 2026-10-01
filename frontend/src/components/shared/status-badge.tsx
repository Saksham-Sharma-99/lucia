import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  active: "text-success border-success/40",
  connected: "text-success border-success/40",
  ok: "text-success border-success/40",
  pass: "text-success border-success/40",
  ready: "text-success border-success/40",
  template: "text-brass border-brass/40",
  "needs setup": "text-brass border-brass/40",
  pending: "text-brass border-brass/40",
  degraded: "text-brass border-brass/40",
  unknown: "text-muted-foreground border-border",
  never: "text-muted-foreground border-border",
  "coming soon": "text-muted-foreground border-border",
  archived: "text-muted-foreground border-border",
  inactive: "text-muted-foreground border-border",
  error: "text-destructive border-destructive/40",
  stopped: "text-destructive border-destructive/40",
  fail: "text-destructive border-destructive/40",
  revoked: "text-destructive border-destructive/40",
};

/** A status as a small outlined pill; the dot carries the colour for quick scanning. */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = TONE[status] ?? TONE.unknown;
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap",
        tone,
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}
