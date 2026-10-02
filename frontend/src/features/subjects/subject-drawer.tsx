import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRightIcon, BriefcaseIcon, PencilIcon } from "lucide-react";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";

import {
  createSubjectMutation,
  getSubjectOptions,
  listSubjectKindsOptions,
  updateSubjectMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { SubjectDetail } from "@/api/generated/types.gen";
import { QueryState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { ContactsSection } from "./contacts-section";
import { blankSubject, changed, subjectSchema, toBody, toForm, type SubjectForm } from "./model";
import { SubjectFields } from "./subject-form";

/**
 * A subject in a side drawer: create one (`subjectId="new"`), or view it with its contacts,
 * consent and runs, and edit it unless `readOnly` (opened from a chat).
 */
export function SubjectDrawer({
  firmId,
  subjectId,
  readOnly,
  onOpen,
  onClose,
}: {
  firmId: string;
  subjectId: string;
  readOnly?: boolean;
  /** After a create: show the new subject. */
  onOpen?: (subjectId: string) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open onOpenChange={(open) => open || onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {subjectId === "new" ? (
          <NewSubject firmId={firmId} onCreated={(id) => onOpen?.(id)} />
        ) : (
          <ExistingSubject firmId={firmId} subjectId={subjectId} readOnly={readOnly} />
        )}
      </SheetContent>
    </Sheet>
  );
}

function useKinds(firmId: string) {
  return useQuery(listSubjectKindsOptions({ path: { firm_id: firmId } })).data ?? [];
}

function NewSubject({ firmId, onCreated }: { firmId: string; onCreated: (id: string) => void }) {
  const kinds = useKinds(firmId);
  const form = useForm<SubjectForm>({
    resolver: zodResolver(subjectSchema),
    defaultValues: blankSubject,
  });
  const create = useApiMutation(
    {
      ...createSubjectMutation(),
      onSuccess: (s) => onCreated(s.id),
      onError: (e) => showFormErrors(form.setError, e),
    },
    { stale: STALE.subject, success: (s) => `Added ${s.title}`, error: false },
  );
  return (
    <FormProvider {...form}>
      <form
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit((f) =>
          create.mutate({ path: { firm_id: firmId }, body: toBody(f) }),
        )}
      >
        <SheetHeader className="p-0 px-6 pt-6">
          <SheetTitle>New subject</SheetTitle>
          <SheetDescription>
            What agents will work on: add contacts once it exists.
          </SheetDescription>
        </SheetHeader>
        <div className="px-6">
          <SubjectFields kinds={kinds} />
          <RootError message={form.formState.errors.root?.message} />
        </div>
        <div className="px-6 pb-6">
          <Button type="submit" disabled={create.isPending}>
            Create subject
          </Button>
        </div>
      </form>
    </FormProvider>
  );
}

function ExistingSubject({
  firmId,
  subjectId,
  readOnly,
}: {
  firmId: string;
  subjectId: string;
  readOnly?: boolean;
}) {
  const subject = useQuery(getSubjectOptions({ path: { subject_id: subjectId } }));
  const [editing, setEditing] = useState(false);
  return (
    <QueryState query={subject} what="This subject" loading={<Skeleton className="m-6 h-64" />}>
      {(s) =>
        editing ? (
          <EditSubject firmId={firmId} subject={s} onDone={() => setEditing(false)} />
        ) : (
          <div className="flex flex-col gap-6 p-6">
            <SheetHeader className="p-0">
              <div className="flex items-start gap-3 pr-8">
                <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-md">
                  <BriefcaseIcon className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <SheetTitle className="text-lg">{s.title}</SheetTitle>
                  <SheetDescription className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{s.kind}</Badge>
                    {s.external_ref && <span className="font-mono">{s.external_ref}</span>}
                    <StatusBadge status={s.status} />
                  </SheetDescription>
                </div>
                {!readOnly && (
                  <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                    <PencilIcon /> Edit
                  </Button>
                )}
              </div>
            </SheetHeader>
            {s.description && <p className="text-muted-foreground text-sm">{s.description}</p>}
            <ContactsSection firmId={firmId} subject={s} readOnly={readOnly} />
            <RunsSection subject={s} />
          </div>
        )
      }
    </QueryState>
  );
}

function EditSubject({
  firmId,
  subject,
  onDone,
}: {
  firmId: string;
  subject: SubjectDetail;
  onDone: () => void;
}) {
  const kinds = useKinds(firmId);
  const before = toForm(subject);
  const form = useForm<SubjectForm>({
    resolver: zodResolver(subjectSchema),
    defaultValues: before,
  });
  const save = useApiMutation(
    {
      ...updateSubjectMutation(),
      onSuccess: onDone,
      onError: (e) => showFormErrors(form.setError, e),
    },
    { stale: STALE.subject, success: "Saved", error: false },
  );
  return (
    <FormProvider {...form}>
      <form
        className="flex flex-col gap-4 p-6"
        onSubmit={form.handleSubmit((f) => {
          const body = changed(before, f);
          if (Object.keys(body).length === 0) return onDone();
          save.mutate({ path: { subject_id: subject.id }, body });
        })}
      >
        <SheetHeader className="p-0">
          <SheetTitle>Edit subject</SheetTitle>
        </SheetHeader>
        <SubjectFields kinds={kinds} />
        <RootError message={form.formState.errors.root?.message} />
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </form>
    </FormProvider>
  );
}

function RunsSection({ subject }: { subject: SubjectDetail }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">Runs on this subject</h3>
      {subject.runs.length === 0 ? (
        <p className="text-muted-foreground text-sm">No agent has worked on it yet.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {subject.runs.map((r) => (
            <li key={r.id}>
              <Link
                to="/runs/$runId"
                params={{ runId: r.id }}
                className="hover:bg-muted flex items-center gap-3 px-3 py-2 text-sm"
              >
                <span className="font-medium">@{r.agent_handle}</span>
                <StatusBadge status={r.status.toLowerCase()} />
                <ArrowUpRightIcon className="text-muted-foreground ml-auto size-4" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RootError({ message }: { message?: string }) {
  return message ? (
    <p role="alert" className="text-destructive mt-2 text-sm">
      {message}
    </p>
  ) : null;
}
