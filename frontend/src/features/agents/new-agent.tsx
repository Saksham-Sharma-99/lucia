import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { FormProvider, useForm, useWatch, type FieldErrors } from "react-hook-form";
import { toast } from "sonner";

import {
  createAgentMutation,
  getAgentOptions,
  getAgentVersionOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { LeaveGuard } from "@/components/shared/leave-guard";
import { PageHeader } from "@/components/shared/page-header";
import { QueryState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useRegistry, type Registry } from "@/features/registry/use-registry";
import { STALE } from "@/lib/invalidate";
import { applyFieldErrors, isProblem, pointerToField, problemMessage } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { blankConfig, toForm, toPayload } from "./config";
import { DraftedStep } from "./drafter/drafted-step";
import { useWizardDrafter } from "./drafter/use-wizard-drafter";
import { Wand } from "./drafter/wand";
import {
  SECTIONS,
  agentFormSchema,
  sectionFor,
  useServerValidation,
  type SectionId,
} from "./editor";
import { OrchestrationDiagram } from "./orchestration-diagram";
import { SECTION_VIEWS } from "./section-views";
import type { AgentForm } from "./sections";
import { ServerCheckBadge, ServerCheckPanel } from "./server-check";
import { StartStep, StepNav } from "./wizard-steps";

type Step = "start" | SectionId | "review";
const STEPS: { id: Step; label: string }[] = [
  { id: "start", label: "Start" },
  ...SECTIONS.map((s) => ({ id: s.id as Step, label: s.label })),
  { id: "review", label: "Review" },
];
const loading = <Skeleton className="h-96 w-full" />;

export function NewAgent({ template }: { template?: string }) {
  const registry = useRegistry();
  return (
    <QueryState query={registry} what="The registry" loading={loading}>
      {(reg) =>
        template ? (
          <FromTemplate handle={template} registry={reg} />
        ) : (
          <Wizard initial={blank(reg)} startAt="start" registry={reg} />
        )
      }
    </QueryState>
  );
}

const blank = (registry: Registry): AgentForm => ({
  handle: "",
  name: "",
  description: "",
  use_cases: [],
  config: blankConfig(registry.models),
  changelog: "",
});

/** Prefill every step from a template's latest active version (?template=records). */
function FromTemplate({ handle, registry }: { handle: string; registry: Registry }) {
  const tpl = useQuery(getAgentOptions({ path: { handle } }));
  const latest = tpl.data?.versions.find((v) => v.status === "active")?.version;
  const version = useQuery({
    ...getAgentVersionOptions({ path: { handle, n: latest ?? 0 } }),
    enabled: !!latest,
  });
  if (tpl.isPending || (latest && version.isPending)) return loading;
  if (tpl.isError || version.isError || !tpl.data || !version.data)
    return (
      <EmptyState
        title={`Template @${handle} can't be used`}
        description={
          tpl.isError || version.isError
            ? problemMessage(tpl.error ?? version.error)
            : "It has no active version."
        }
      />
    );
  const initial: AgentForm = {
    handle: "",
    name: tpl.data.name,
    description: tpl.data.description,
    use_cases: tpl.data.use_cases,
    config: toForm(version.data.config),
    changelog: `Started from the @${tpl.data.handle} template`,
  };
  return <Wizard sourceId={tpl.data.id} initial={initial} startAt="basic" registry={registry} />;
}

/** The first section with a client-side error, for jumping to it. */
function firstErrorSection(errors: FieldErrors<AgentForm>): SectionId | undefined {
  const fields = Object.keys(errors).flatMap((k) =>
    k === "config" ? Object.keys(errors.config ?? {}).map((c) => `config.${c}`) : [k],
  );
  return fields.map(sectionFor).find(Boolean);
}

function Wizard({
  sourceId,
  initial,
  startAt,
  registry,
}: {
  sourceId?: string;
  initial: AgentForm;
  startAt: Step;
  registry: Registry;
}) {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(startAt);
  const form = useForm<AgentForm>({
    resolver: zodResolver(agentFormSchema),
    defaultValues: initial,
  });
  const config = useWatch({ control: form.control, name: "config" });
  const handle = useWatch({ control: form.control, name: "handle" });
  const check = useServerValidation(config, step !== "start");
  const drafter = useWizardDrafter(form, registry);
  const { busy } = drafter;

  const create = useApiMutation(
    {
      ...createAgentMutation(),
      // Saved: leaving is safe, so skip the unsaved-changes guard.
      onSuccess: (agent) =>
        void navigate({
          to: "/agents/$handle",
          params: { handle: agent.handle },
          search: { tab: "overview" },
          ignoreBlocker: true,
        }),
      onError: (error) => {
        if (isProblem(error) && error.status === 409) {
          form.setError("handle", { message: error.detail ?? "Handle is taken" });
          setStep("basic");
          return;
        }
        applyFieldErrors(form.setError, error).forEach((m) => toast.error(m));
        const first =
          isProblem(error) && error.errors?.[0]
            ? sectionFor(pointerToField(error.errors[0].path))
            : undefined;
        setStep(first ?? "review");
      },
    },
    { stale: STALE.agent, success: (agent) => `Created @${agent.handle} v1`, error: false },
  );

  const index = STEPS.findIndex((s) => s.id === step);
  const next = async () => {
    const section = SECTIONS.find((s) => s.id === step);
    if (section && !(await form.trigger([...section.fields]))) return;
    const to = STEPS[index + 1].id;
    setStep(to);
    drafter.reach(to);
  };
  const submit = form.handleSubmit(
    (v) =>
      create.mutate({
        body: { ...v, config: toPayload(v.config), source_agent_id: sourceId ?? null },
      }),
    (errors) => {
      const section = firstErrorSection(errors);
      if (section) setStep(section);
      toast.error("Some fields need attention");
    },
  );

  return (
    <FormProvider {...form}>
      <LeaveGuard when={form.formState.isDirty} />
      <PageHeader
        title="New agent"
        description="Saving creates version 1. You can amend it later; every amendment is a new version."
      />
      <div className="grid gap-10 lg:grid-cols-[13rem_1fr]">
        <StepNav steps={STEPS} current={step} onStep={setStep} disabled={busy} />
        <form onSubmit={(e) => e.preventDefault()} className="min-w-0">
          {step === "start" && (
            <StartStep
              onPick={(h) => void navigate({ to: "/agents/new", search: { template: h } })}
              onBlank={() => setStep("basic")}
            />
          )}
          {step !== "start" && step !== "review" && (
            <DraftedStep drafter={drafter} step={step}>
              {SECTION_VIEWS[step]({
                registry,
                disabled: drafter.prompt.streaming,
                assist: (
                  <Wand
                    draft={drafter.prompt}
                    enabled={registry.platform.drafter_enabled}
                    prefill={form.getValues("description")}
                  />
                ),
              })}
            </DraftedStep>
          )}
          {step === "review" && (
            <div className="space-y-8">
              <OrchestrationDiagram
                handle={handle || "new-agent"}
                config={config}
                registry={registry}
              />
              <ServerCheckPanel check={check} onJump={setStep} />
              <Field className="max-w-xl">
                <FieldLabel htmlFor="changelog">Version note (optional)</FieldLabel>
                <Textarea
                  id="changelog"
                  rows={2}
                  placeholder="What this first version does"
                  {...form.register("changelog")}
                />
              </Field>
            </div>
          )}
          {step !== "start" && (
            <div className="border-border mt-8 flex items-center justify-between border-t pt-4">
              <Button variant="ghost" disabled={busy} onClick={() => setStep(STEPS[index - 1].id)}>
                Back
              </Button>
              <div className="flex items-center gap-4">
                {step === "review" ? (
                  <Button onClick={() => void submit()} disabled={create.isPending}>
                    {create.isPending ? "Creating…" : "Create agent"}
                  </Button>
                ) : (
                  <>
                    <ServerCheckBadge check={check} />
                    <Button onClick={() => void next()} disabled={busy}>
                      Next
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
        </form>
      </div>
    </FormProvider>
  );
}
