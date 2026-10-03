import { useState } from "react";

import {
  handbackRunMutation,
  takeoverRunMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";

const COPY = {
  takeover: {
    title: "Take over this run",
    description:
      "The agent stops and does nothing until you hand it back. Say what you're doing, so the record and the agent know.",
    button: "Take over",
    done: "You've taken over the run",
  },
  handback: {
    title: "Hand the run back",
    description: "The agent reads your remarks first, then carries on from where things stand.",
    button: "Hand back",
    done: "Handed back to the agent",
  },
} as const;

/** Take over or hand back a run, with the remarks both require (10–2000 characters). */
export function ControlDialog({
  action,
  runId,
  onClose,
}: {
  action: "takeover" | "handback";
  runId: string;
  onClose: () => void;
}) {
  const [remarks, setRemarks] = useState("");
  const copy = COPY[action];
  const mutation = action === "takeover" ? takeoverRunMutation() : handbackRunMutation();
  const send = useApiMutation(
    { ...mutation, onSuccess: onClose },
    { stale: STALE.run, success: copy.done },
  );
  const valid = remarks.trim().length >= 10 && remarks.length <= 2000;
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) send.mutate({ path: { run_id: runId }, body: { remarks: remarks.trim() } });
          }}
        >
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>{copy.description}</DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-2">
            <Label htmlFor="control-remarks">Remarks</Label>
            <Textarea
              id="control-remarks"
              rows={4}
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="At least 10 characters"
            />
          </div>
          <DialogFooter className="mt-4">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!valid || send.isPending}>
              {copy.button}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
