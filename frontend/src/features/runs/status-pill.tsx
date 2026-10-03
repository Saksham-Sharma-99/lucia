import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleDotIcon,
  CircleIcon,
  CirclePauseIcon,
  CircleXIcon,
  ClockIcon,
  HandIcon,
  HourglassIcon,
  MessageSquareIcon,
  PhoneIncomingIcon,
  RotateCwIcon,
  UserCheckIcon,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { statusLabel } from "./model";

const LOOK: Record<string, { tone: string; icon: LucideIcon }> = {
  ACTIVE: { tone: "bg-primary/10 text-primary", icon: CircleDotIcon },
  RUNNING: { tone: "bg-primary/10 text-primary", icon: CircleDotIcon },
  IN_PROGRESS: { tone: "bg-primary/10 text-primary", icon: CircleDotIcon },
  CREATED: { tone: "bg-muted text-muted-foreground", icon: CircleIcon },
  TODO: { tone: "bg-muted text-muted-foreground", icon: CircleIcon },
  PENDING: { tone: "bg-muted text-muted-foreground", icon: CircleIcon },
  WAITING: { tone: "bg-amber-500/10 text-amber-700 dark:text-amber-400", icon: HourglassIcon },
  AWAITING_CALLBACK: {
    tone: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
    icon: HourglassIcon,
  },
  AWAITING_CONFIRMATION: {
    tone: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300",
    icon: HourglassIcon,
  },
  BLOCKED: { tone: "bg-orange-500/10 text-orange-700 dark:text-orange-400", icon: CirclePauseIcon },
  PAUSED: { tone: "bg-orange-500/10 text-orange-700 dark:text-orange-400", icon: CirclePauseIcon },
  TAKEN_OVER: { tone: "bg-brass/15 text-brass", icon: HandIcon },
  DONE: { tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400", icon: CircleCheckIcon },
  COMPLETED: {
    tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    icon: CircleCheckIcon,
  },
  SUCCEEDED: {
    tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    icon: CircleCheckIcon,
  },
  SKIPPED: { tone: "bg-muted text-muted-foreground", icon: CircleDashedIcon },
  SUPERSEDED: { tone: "bg-muted text-muted-foreground", icon: CircleDashedIcon },
  ENDED: { tone: "bg-muted text-muted-foreground", icon: CircleDashedIcon },
  FAILED: { tone: "bg-destructive/10 text-destructive", icon: CircleXIcon },
  BLOCKED_BY_POLICY: { tone: "bg-destructive/10 text-destructive", icon: CircleXIcon },
  BLOCKED_BY_GUARDRAIL: { tone: "bg-destructive/10 text-destructive", icon: CircleXIcon },
};

/** A runtime status (run, task, item, step) as a soft pill with an icon and words. */
export function StatusPill({ status, className }: { status: string; className?: string }) {
  const { tone, icon: Icon } = LOOK[status] ?? LOOK.PENDING;
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap",
        tone,
        className,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {statusLabel(status)}
    </span>
  );
}

/** Just the coloured icon (lists of items and tasks). */
export function StatusIcon({ status, className }: { status: string; className?: string }) {
  const { tone, icon: Icon } = LOOK[status] ?? LOOK.PENDING;
  return (
    <span
      aria-label={statusLabel(status)}
      className={cn(
        "inline-flex size-6 shrink-0 items-center justify-center rounded-full",
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" />
    </span>
  );
}

const TRIGGER_ICON: Record<string, LucideIcon> = {
  user_input: MessageSquareIcon,
  external_response: PhoneIncomingIcon,
  scheduled: ClockIcon,
  user_response: UserCheckIcon,
  handback: HandIcon,
  retry: RotateCwIcon,
};

/** What woke the run, as an icon (a message, a call report, a timer…). */
export function TriggerIcon({ trigger, className }: { trigger: string; className?: string }) {
  const Icon = TRIGGER_ICON[trigger] ?? ClockIcon;
  return <Icon className={className} />;
}
