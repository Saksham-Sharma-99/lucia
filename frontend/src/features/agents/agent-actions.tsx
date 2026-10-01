import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useState, type ReactElement } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  archiveAgentMutation,
  duplicateAgentMutation,
  unarchiveAgentMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { AffectedMappings } from "@/features/mappings/affected-mappings";
import { useActiveMappings } from "@/features/mappings/hooks";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { handleSchema } from "./config";

type Agent = { id: string; handle: string; name: string; status: "active" | "archived" };
type Choice = "duplicate" | "archive" | null;

/**
 * The agent actions menu, for list rows and the detail header. Dialogs mount only when chosen,
 * so each opens fresh and idle rows cost nothing.
 */
export function AgentActionsMenu({
  agent,
  amendFrom,
  trigger,
}: {
  agent: Agent;
  /** List rows add View and "Amend v{amendFrom}"; the detail page has its own Amend button. */
  amendFrom?: number;
  trigger: ReactElement;
}) {
  const navigate = useNavigate();
  const [choice, setChoice] = useState<Choice>(null);
  const archived = agent.status === "archived";
  const close = () => setChoice(null);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger render={trigger} />
        <DropdownMenuContent align="end">
          {amendFrom !== undefined && (
            <>
              <DropdownMenuItem
                onClick={() =>
                  void navigate({
                    to: "/agents/$handle",
                    params: { handle: agent.handle },
                    search: { tab: "overview" },
                  })
                }
              >
                View
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={archived}
                onClick={() =>
                  void navigate({
                    to: "/agents/$handle/amend",
                    params: { handle: agent.handle },
                    search: { from: amendFrom },
                  })
                }
              >
                Amend v{amendFrom}
              </DropdownMenuItem>
            </>
          )}
          <DropdownMenuItem disabled={archived} onClick={() => setChoice("duplicate")}>
            Duplicate
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant={archived ? "default" : "destructive"}
            onClick={() => setChoice("archive")}
          >
            {archived ? "Unarchive" : "Archive"}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {choice === "duplicate" && <DuplicateDialog agent={agent} onClose={close} />}
      {choice === "archive" &&
        (archived ? (
          <UnarchiveDialog agent={agent} onClose={close} />
        ) : (
          <ArchiveDialog agent={agent} onClose={close} />
        ))}
    </>
  );
}

const duplicateSchema = z.object({
  handle: handleSchema,
  name: z.string().trim().min(1, "Name the copy").max(120),
});

export function DuplicateDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const navigate = useNavigate();
  const form = useForm({
    resolver: zodResolver(duplicateSchema),
    defaultValues: { handle: `${agent.handle}-copy`.slice(0, 32), name: `${agent.name} (copy)` },
  });
  const duplicate = useApiMutation(
    {
      ...duplicateAgentMutation(),
      onSuccess: (copy) => {
        onClose();
        void navigate({
          to: "/agents/$handle",
          params: { handle: copy.handle },
          search: { tab: "overview" },
        });
      },
      onError: (e) => showFormErrors(form.setError, e),
    },
    { stale: STALE.agent, success: (copy) => `Created @${copy.handle}`, error: false },
  );
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent>
        <form
          onSubmit={form.handleSubmit((body) =>
            duplicate.mutate({ path: { handle: agent.handle }, body }),
          )}
        >
          <DialogHeader>
            <DialogTitle>Duplicate @{agent.handle}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground my-3 text-sm">
            The copy starts at v1 with the latest active version's config.
          </p>
          <div className="space-y-4">
            <Field data-invalid={!!errors.handle}>
              <FieldLabel htmlFor="dup-handle">Handle</FieldLabel>
              <Input id="dup-handle" className="font-mono" {...form.register("handle")} />
              <FieldError errors={[errors.handle]} />
            </Field>
            <Field data-invalid={!!errors.name}>
              <FieldLabel htmlFor="dup-name">Name</FieldLabel>
              <Input id="dup-name" {...form.register("name")} />
              <FieldError errors={[errors.name]} />
            </Field>
            {errors.root && (
              <p role="alert" className="text-destructive text-sm">
                {errors.root.message}
              </p>
            )}
          </div>
          <DialogFooter className="mt-6">
            <Button type="submit" disabled={duplicate.isPending}>
              Duplicate
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Archive lists the mappings it will turn off, so nobody is surprised. */
export function ArchiveDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const affected = useActiveMappings({ agent_id: agent.id });
  const archive = useApiMutation(archiveAgentMutation(), {
    stale: [...STALE.agent, ...STALE.mapping],
    success: (r) => {
      const n = r.deactivated_mapping_ids.length;
      return `Archived @${agent.handle}${n ? `; ${n} mapping${n > 1 ? "s" : ""} turned off` : ""}`;
    },
    error: "Archive failed",
  });
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => open || onClose()}
      title={`Archive @${agent.handle}?`}
      destructive
      confirmLabel="Archive"
      confirmDisabled={affected.isPending}
      onConfirm={() => archive.mutate({ path: { handle: agent.handle } })}
      description={
        <AffectedMappings
          query={affected}
          intro="Every version is archived and these mappings are turned off:"
          none="Every version is archived. No firm is using it right now."
          name={(m) => `${m.firm_name} (v${m.version})`}
        />
      }
    />
  );
}

export function UnarchiveDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const unarchive = useApiMutation(unarchiveAgentMutation(), {
    stale: [...STALE.agent, ...STALE.mapping],
    success: `Unarchived @${agent.handle}`,
    error: "Unarchive failed",
  });
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => open || onClose()}
      title={`Unarchive @${agent.handle}?`}
      description="Its latest version becomes active again. Mappings stay off until you turn them on."
      confirmLabel="Unarchive"
      onConfirm={() => unarchive.mutate({ path: { handle: agent.handle } })}
    />
  );
}
