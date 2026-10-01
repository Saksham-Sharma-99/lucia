import { zodResolver } from "@hookform/resolvers/zod";
import { PencilIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { updateAgentMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { AgentDetail, VersionDetail } from "@/api/generated/types.gen";
import { TagInput } from "@/components/shared/controls";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Registry } from "@/features/registry/use-registry";
import { dateTime, shortHash } from "@/lib/format";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import type { ConfigForm } from "./config";
import { OrchestrationDiagram } from "./orchestration-diagram";

export function OverviewTab({
  agent,
  version,
  config,
  registry,
}: {
  agent: AgentDetail;
  version: VersionDetail;
  config: ConfigForm;
  registry: Registry;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="grid gap-8 lg:min-h-0 lg:flex-1 lg:grid-cols-2 lg:gap-0">
      <div className="space-y-8 lg:overflow-y-auto lg:border-r lg:pr-8 lg:pb-8">
        <section>
          <SectionHeading
            title="About"
            description="Changing these doesn't create a new version."
            action={
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <PencilIcon /> Edit
              </Button>
            }
          />
          <dl className="space-y-4 text-sm">
            <Fact label="Name">{agent.name}</Fact>
            <Fact label="Description">{agent.description || "—"}</Fact>
            <Fact label="Example prompts">
              {agent.use_cases.length ? (
                <ul className="space-y-1">
                  {agent.use_cases.map((u) => (
                    <li key={u}>“{u}”</li>
                  ))}
                </ul>
              ) : (
                "—"
              )}
            </Fact>
          </dl>
        </section>
        <section className="border-t pt-8">
          <SectionHeading
            title={`Version ${version.version}`}
            description={version.changelog || "No version note."}
          />
          <dl className="space-y-4 text-sm">
            <Fact label="Status">
              <StatusBadge status={version.status} />
            </Fact>
            <Fact label="Saved">
              {dateTime(version.created_at)} by {version.created_by_name}
            </Fact>
            {version.parent_version && <Fact label="Amended from">v{version.parent_version}</Fact>}
            <Fact label="Config hash">
              <code className="font-mono text-xs" title={version.config_hash}>
                {shortHash(version.config_hash)}
              </code>
            </Fact>
          </dl>
        </section>
      </div>
      {/* A dotted canvas the diagram's nodes float on, filling its pane; it scrolls on its own. */}
      <aside className="rounded-xl border bg-[radial-gradient(var(--color-border)_1px,transparent_1px)] [background-size:18px_18px] p-6 lg:ml-8 lg:h-full lg:overflow-y-auto">
        <SectionHeading title="How it works" description="Drawn from this version's config." />
        <OrchestrationDiagram handle={agent.handle} config={config} registry={registry} />
      </aside>
      {editing && <EditAgentDialog agent={agent} onClose={() => setEditing(false)} />}
    </div>
  );
}

function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-muted-foreground text-sm">{description}</p>
      </div>
      {action}
    </div>
  );
}

/** A label with its value underneath. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-muted-foreground mb-0.5 text-xs">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const editSchema = z.object({
  name: z.string().trim().min(1, "Name the agent").max(120),
  description: z.string().max(2000),
  use_cases: z.array(z.string()).max(20),
});

function EditAgentDialog({ agent, onClose }: { agent: AgentDetail; onClose: () => void }) {
  const form = useForm({
    resolver: zodResolver(editSchema),
    defaultValues: { name: agent.name, description: agent.description, use_cases: agent.use_cases },
  });
  const update = useApiMutation(
    {
      ...updateAgentMutation(),
      onSuccess: onClose,
      onError: (e) => showFormErrors(form.setError, e),
    },
    { stale: STALE.agent, success: "Saved", error: false },
  );
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form
          onSubmit={form.handleSubmit((body) =>
            update.mutate({ path: { handle: agent.handle }, body }),
          )}
        >
          <DialogHeader>
            <DialogTitle>Edit @{agent.handle}</DialogTitle>
          </DialogHeader>
          <div className="mt-4 space-y-4">
            <Field data-invalid={!!errors.name}>
              <FieldLabel htmlFor="edit-name">Name</FieldLabel>
              <Input id="edit-name" {...form.register("name")} />
              <FieldError errors={[errors.name]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="edit-description">Description</FieldLabel>
              <Textarea id="edit-description" rows={3} {...form.register("description")} />
            </Field>
            <Field>
              <FieldLabel>Example prompts</FieldLabel>
              <Controller
                control={form.control}
                name="use_cases"
                render={({ field }) => <TagInput value={field.value} onChange={field.onChange} />}
              />
            </Field>
            {errors.root && (
              <p role="alert" className="text-destructive text-sm">
                {errors.root.message}
              </p>
            )}
          </div>
          <DialogFooter className="mt-6">
            <Button type="submit" disabled={update.isPending}>
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
