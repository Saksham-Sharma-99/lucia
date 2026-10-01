import { CheckCircle2Icon, CircleAlertIcon, LoaderIcon } from "lucide-react";

import { pointerToField } from "@/lib/problem";

import { SECTIONS, sectionFor, type SectionId, type ServerCheck } from "./editor";

/** The server's verdict on the config, with each issue linked to the section that owns it. */
export function ServerCheckPanel({
  check,
  onJump,
}: {
  check: ServerCheck;
  onJump: (s: SectionId) => void;
}) {
  if (check.state === "idle") return null;
  if (check.state === "checking")
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm">
        <LoaderIcon className="size-4 animate-spin" /> Checking with the server…
      </p>
    );
  if (check.state === "ok")
    return (
      <p className="text-success flex items-center gap-2 text-sm">
        <CheckCircle2Icon className="size-4" /> The server accepts this config.
      </p>
    );
  return (
    <div className="border-destructive/40 rounded-lg border p-3">
      <p className="text-destructive flex items-center gap-2 text-sm font-medium">
        <CircleAlertIcon className="size-4" /> {check.errors.length} issue
        {check.errors.length === 1 ? "" : "s"} to fix
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {check.errors.map((e, i) => {
          const section = sectionFor(pointerToField(e.path));
          return (
            <li key={i}>
              {section ? (
                <button
                  type="button"
                  className="text-left hover:underline"
                  onClick={() => onJump(section)}
                >
                  <span className="text-muted-foreground">
                    {SECTIONS.find((s) => s.id === section)?.label}:
                  </span>{" "}
                  {e.message}
                </button>
              ) : (
                e.message
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** One-line server status for step footers. */
export function ServerCheckBadge({ check }: { check: ServerCheck }) {
  if (check.state === "checking")
    return <span className="text-muted-foreground text-sm">Checking…</span>;
  if (check.state === "ok")
    return <span className="text-success text-sm">Server check passed</span>;
  if (check.state === "invalid")
    return (
      <span className="text-destructive text-sm">
        {check.errors.length} issue{check.errors.length === 1 ? "" : "s"} · see Review
      </span>
    );
  return null;
}
