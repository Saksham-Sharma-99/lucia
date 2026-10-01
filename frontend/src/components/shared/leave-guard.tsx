import { useBlocker } from "@tanstack/react-router";

/** Warns before leaving a page with unsaved changes (route changes and tab close). */
export function LeaveGuard({ when }: { when: boolean }) {
  useBlocker({
    shouldBlockFn: () => !window.confirm("You have unsaved changes. Leave without saving?"),
    enableBeforeUnload: () => when,
    disabled: !when,
  });
  return null;
}
