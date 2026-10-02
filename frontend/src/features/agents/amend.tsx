import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  createAgentVersionMutation,
  getAgentOptions,
  getAgentVersionOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { AgentDetail } from "@/api/generated/types.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { LeaveGuard } from "@/components/shared/leave-guard";
import { PageHeader } from "@/components/shared/page-header";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useRegistry, type Registry } from "@/features/registry/use-registry";
import { STALE } from "@/lib/invalidate";
import { applyFieldErrors, isProblem, pointerToField } from "@/lib/problem";
import { allOf } from "@/lib/query";
import { useApiMutation } from "@/lib/use-api-mutation";

import { configSchema, toForm, toPayload, type ConfigForm } from "./config";
import { DRAFT_SECTIONS, draftContext } from "./drafter/draft";
import { usePromptDraft } from "./drafter/use-prompt-draft";
import { Wand } from "./drafter/wand";
import {
  AMEND_SECTIONS,
  changedSections,
  sectionFor,
  useServerValidation,
  type AmendSection,
} from "./editor";
import { SECTION_VIEWS } from "./section-views";
import type { AgentForm } from "./sections";
import { ServerCheckPanel } from "./server-check";

// Amend edits only the config (the agent's own fields are edited on the overview). The section
// views read `config.*` from the shared AgentForm shape, which this is a part of.
const amendSchema = z.object({
  config: configSchema,
  changelog: z.string().trim().min(1, "Say what changed").max(2000),
});
type AmendForm = Pick<AgentForm, "config" | "changelog">;

export function AmendPage({ handle, from }: { handle: string; from: number }) {
  const page = allOf({
    agent: useQuery(getAgentOptions({ path: { handle } })),
    base: useQuery(getAgentVersionOptions({ path: { handle, n: from } })),
    registry: useRegistry(),
  });
  return (
    <QueryState
      query={page}
      what={`@${handle} v${from}`}
      loading={<Skeleton className="h-96 w-full" />}
    >
      {({ agent, base, registry }) =>
        agent.status === "archived" ? (
          <EmptyState
            title={`@${handle} is archived`}
            description="Unarchive it before amending."
            action={
              <Button
                nativeButton={false}
                render={
                  <Link to="/agents/$handle" params={{ handle }} search={{ tab: "overview" }} />
                }
              >
                Back to agent
              </Button>
            }
          />
        ) : (
          <AmendForm agent={agent} from={from} base={toForm(base.config)} registry={registry} />
        )
      }
    </QueryState>
  );
}

function AmendForm({
  agent,
  from,
  base,
  registry,
}: {
  agent: AgentDetail;
  from: number;
  base: ConfigForm;
  registry: Registry;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<AmendSection>("capabilities");
  const nextVersion = Math.max(...agent.versions.map((v) => v.version)) + 1;
  const form = useForm<AmendForm>({
    resolver: zodResolver(amendSchema),
    defaultValues: { config: base, changelog: "" },
  });
  const config = useWatch({ control: form.control, name: "config" });
  const check = useServerValidation(config);
  const changed = useMemo(() => changedSections(base, config), [base, config]);
  // Amend gets the wand only: it refines the prompt, and never drafts the other tabs.
  const prompt = usePromptDraft(form, {
    basic: () => ({ name: agent.name, description: agent.description, use_cases: agent.use_cases }),
    // An amended version is fully set up, so every step is context.
    context: () => draftContext(form.getValues("config"), DRAFT_SECTIONS),
  });
  const wand = (
    <Wand draft={prompt} enabled={registry.platform.drafter_enabled} prefill={agent.description} />
  );

  const save = useApiMutation(
    {
      ...createAgentVersionMutation(),
      onSuccess: (v) => {
        void navigate({
          to: "/agents/$handle",
          params: { handle: agent.handle },
          search: { tab: "overview", v: v.version },
          ignoreBlocker: true, // saved: leaving is safe
        });
      },
      onError: (error) => {
        applyFieldErrors(form.setError, error).forEach((m) => toast.error(m));
        const first =
          isProblem(error) && error.errors?.[0]
            ? sectionFor(pointerToField(error.errors[0].path))
            : undefined;
        if (first && first !== "basic") setTab(first);
      },
    },
    { stale: STALE.agent, success: (v) => `Saved v${v.version}`, error: false },
  );
  const submit = form.handleSubmit(
    (v) =>
      save.mutate({
        path: { handle: agent.handle },
        body: { from_version: from, config: toPayload(v.config), changelog: v.changelog },
      }),
    (errors) => {
      const field = Object.keys(errors.config ?? {})[0];
      const section = field ? sectionFor(`config.${field}`) : undefined;
      if (section && section !== "basic") setTab(section);
    },
  );
  return (
    <FormProvider {...form}>
      <LeaveGuard when={form.formState.isDirty} />
      <PageHeader
        title={
          <>
            Amend <span className="font-mono">@{agent.handle}</span> from v{from}
          </>
        }
        description={`Nothing is saved until you save. v${from} stays as it is; this becomes v${nextVersion}.`}
      />
      <Tabs value={tab} onValueChange={(t) => setTab(t as AmendSection)}>
        <TabsList variant="line" className="mb-6">
          {AMEND_SECTIONS.map((s) => (
            <TabsTrigger key={s.id} value={s.id}>
              {s.label}
              {changed.has(s.id) && (
                <span aria-label="changed" className="bg-brass ml-1.5 size-1.5 rounded-full" />
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        {AMEND_SECTIONS.map((s) => (
          <TabsContent key={s.id} value={s.id}>
            {SECTION_VIEWS[s.id]({ registry, disabled: prompt.streaming, assist: wand })}
          </TabsContent>
        ))}
      </Tabs>
      <div className="bg-background/95 border-border sticky bottom-0 mt-8 grid gap-4 border-t py-4 backdrop-blur md:grid-cols-[1fr_auto]">
        <div className="space-y-3">
          <Field className="max-w-xl" data-invalid={!!form.formState.errors.changelog}>
            <FieldLabel htmlFor="changelog">What changed</FieldLabel>
            <Textarea
              id="changelog"
              rows={2}
              placeholder="e.g. Call before the second email"
              {...form.register("changelog")}
            />
            <FieldError errors={[form.formState.errors.changelog]} />
          </Field>
          <ServerCheckPanel check={check} onJump={(s) => s !== "basic" && setTab(s)} />
        </div>
        <div className="flex items-end gap-2">
          <Button
            variant="ghost"
            nativeButton={false}
            render={
              <Link
                to="/agents/$handle"
                params={{ handle: agent.handle }}
                search={{ tab: "overview" }}
              />
            }
          >
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={save.isPending || prompt.streaming || changed.size === 0}
          >
            {save.isPending ? "Saving…" : `Save as v${nextVersion}`}
          </Button>
        </div>
      </div>
    </FormProvider>
  );
}
