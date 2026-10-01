import type { ReactNode } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { isProblem, problemMessage } from "@/lib/problem";

export function Problems({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="text-destructive space-y-1 text-sm">
      <p>{problemMessage(error)}</p>
      {isProblem(error) && error.errors?.map((e, i) => <p key={i}>{e.message}</p>)}
    </div>
  );
}

export function ShellDialog({
  title,
  description,
  onClose,
  children,
  footer,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-6">{children}</div>
        <DialogFooter className="mt-4">{footer}</DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
