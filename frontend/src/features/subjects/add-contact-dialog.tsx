import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";

import {
  createContactPointMutation,
  linkSubjectContactMutation,
  listContactPointsOptions,
} from "@/api/generated/@tanstack/react-query.gen";
import type { SubjectContactCreate } from "@/api/generated/types.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { SearchInput } from "@/components/shared/search-input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { STALE, invalidate } from "@/lib/invalidate";
import { showFormErrors, toastError } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { ContactFields } from "./contact-fields";
import { blankContact, contactBody, type ContactForm } from "./contact-form";
import { cn } from "@/lib/utils";

type Role = SubjectContactCreate["role"];
const ROLES: Role[] = ["client", "provider", "insurer", "prospect", "other"];

/** Put a person on the subject: one of the firm's existing contacts, or a new one. */
export function AddContactDialog({
  firmId,
  subjectId,
  linked,
  onClose,
}: {
  firmId: string;
  subjectId: string;
  /** Contact points already on the subject (not offered again). */
  linked: string[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"existing" | "new">("existing");
  const [role, setRole] = useState<Role>("client");
  const [q, setQ] = useState<string>();
  const [picked, setPicked] = useState<string | null>(null);
  const form = useForm<ContactForm>({ defaultValues: blankContact });
  const candidates = useQuery(
    listContactPointsOptions({ path: { firm_id: firmId }, query: { q, limit: 20 } }),
  );
  const link = useApiMutation(
    { ...linkSubjectContactMutation(), onSuccess: onClose },
    { stale: STALE.subject, success: "Contact added" },
  );
  const create = useApiMutation(
    {
      ...createContactPointMutation(),
      onSuccess: (cp) => {
        void invalidate(queryClient, "listContactPoints");
        link.mutate({
          path: { subject_id: subjectId },
          body: { contact_point_id: cp.id, role },
        });
      },
      onError: (e) => showFormErrors(form.setError, e),
    },
    { error: false },
  );
  const busy = link.isPending || create.isPending;

  const submit = () => {
    if (tab === "existing") {
      if (picked)
        link.mutate({ path: { subject_id: subjectId }, body: { contact_point_id: picked, role } });
      return;
    }
    void form
      .handleSubmit((v) => create.mutate({ path: { firm_id: firmId }, body: contactBody(v) }))()
      .catch((e: unknown) => toastError(e));
  };

  const others = (candidates.data?.items ?? []).filter((c) => !linked.includes(c.id));
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add contact</DialogTitle>
        </DialogHeader>
        <Tabs value={tab} onValueChange={(t) => setTab(t as "existing" | "new")}>
          <TabsList variant="line">
            <TabsTrigger value="existing">Existing contact</TabsTrigger>
            <TabsTrigger value="new">New contact</TabsTrigger>
          </TabsList>
          <TabsContent value="existing" className="space-y-3 pt-3">
            <SearchInput
              label="Search contacts"
              placeholder="Search by name"
              value={q}
              onCommit={setQ}
            />
            {others.length === 0 ? (
              <p className="text-muted-foreground text-sm">No other contacts match.</p>
            ) : (
              <ul className="max-h-56 space-y-1 overflow-y-auto">
                {others.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      aria-pressed={picked === c.id}
                      onClick={() => setPicked(c.id)}
                      className={cn(
                        "hover:bg-muted w-full rounded-md border px-3 py-2 text-left text-sm",
                        picked === c.id && "border-foreground/40 bg-muted",
                      )}
                    >
                      <span className="font-medium">{c.name}</span>
                      <span className="text-muted-foreground block text-xs">
                        {[c.org_name, ...c.emails].filter(Boolean).join(" · ") || "No details"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
          <TabsContent value="new" className="pt-3">
            <FormProvider {...form}>
              <ContactFields />
            </FormProvider>
          </TabsContent>
        </Tabs>
        <Field>
          <FieldLabel>Role on this subject</FieldLabel>
          <SimpleSelect
            label="Role"
            value={role}
            onChange={(r) => setRole(r as Role)}
            options={ROLES.map((r) => ({ value: r, label: r }))}
          />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy || (tab === "existing" && !picked)}>
            Add to subject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
