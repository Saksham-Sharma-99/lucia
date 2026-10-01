import { HashIcon, MailIcon, PhoneIcon, PrinterIcon, PlugIcon } from "lucide-react";

import { CONNECTOR_NAMES } from "@/lib/connectors";
import { cn } from "@/lib/utils";

const ICONS = { slack: HashIcon, gmail: MailIcon, vapi: PhoneIcon, fax: PrinterIcon };

export function ConnectorIcon({ connector, className }: { connector: string; className?: string }) {
  const Icon = ICONS[connector as keyof typeof ICONS] ?? PlugIcon;
  return (
    <span
      title={CONNECTOR_NAMES[connector] ?? connector}
      className={cn(
        "bg-secondary text-secondary-foreground inline-flex size-7 shrink-0 items-center justify-center rounded-md",
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
    </span>
  );
}
