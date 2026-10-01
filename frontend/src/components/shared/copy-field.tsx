import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function CopyField({
  value,
  disabled,
  className,
  label = "Copy",
}: {
  value: string;
  disabled?: boolean;
  className?: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <code
        className={cn(
          "bg-muted min-w-0 flex-1 truncate rounded-md px-2.5 py-1.5 font-mono text-xs",
          disabled && "opacity-50",
        )}
        title={value}
      >
        {value}
      </code>
      <Button variant="outline" size="sm" onClick={copy} disabled={disabled} aria-label={label}>
        {copied ? <CheckIcon /> : <CopyIcon />}
        {copied ? "Copied" : label}
      </Button>
    </div>
  );
}
