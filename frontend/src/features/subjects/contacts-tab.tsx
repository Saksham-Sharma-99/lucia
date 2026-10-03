import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { PencilIcon, PlusIcon } from "lucide-react";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";

import {
  createContactPointMutation,
  listContactPointsOptions,
  updateContactPointMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { ContactPointOut } from "@/api/generated/types.gen";
import { EmptyState } from "@/components/shared/empty-state";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { SearchInput } from "@/components/shared/search-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { STALE } from "@/lib/invalidate";
import { showFormErrors } from "@/lib/problem";
import { useApiMutation } from "@/lib/use-api-mutation";

import { ContactFields } from "./contact-fields";
import { blankContact, contactBody, contactToForm, type ContactForm } from "./contact-form";

/** Everyone a firm's agents may reach, across its subjects. */
export function ContactsTab({ firmId }: { firmId: string }) {
  const [q, setQ] = useState<string>();
  const [pageNo, setPage] = useState(1);
  const [editing, setEditing] = useState<ContactPointOut | "new" | null>(null);
  const contacts = useQuery({
    ...listContactPointsOptions({
      path: { firm_id: firmId },
      query: { q, page: pageNo, limit: 25 },
    }),
    placeholderData: keepPreviousData,
  });
  const add = (
    <Button onClick={() => setEditing("new")}>
      <PlusIcon /> New contact
    </Button>
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-80">
          <SearchInput
            label="Search contacts"
            placeholder="Search name, email or phone"
            value={q}
            onCommit={(next) => {
              setQ(next);
              setPage(1);
            }}
          />
        </div>
        <div className="ml-auto">{add}</div>
      </div>
      <QueryState
        query={contacts}
        what="Contacts"
        isEmpty={(p) => p.total === 0}
        empty={
          q ? (
            <EmptyState title="No contacts match" />
          ) : (
            <EmptyState
              title="No contacts yet"
              description="Clients, providers and insurers the firm's agents may contact. Add them here or from a subject."
              action={add}
            />
          )
        }
      >
        {(p) => (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Timezone</TableHead>
                  <TableHead>Opted out</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <p className="font-medium">{c.name}</p>
                      {c.org_name && <p className="text-muted-foreground text-xs">{c.org_name}</p>}
                    </TableCell>
                    <TableCell>
                      {(c.roles ?? []).length === 0 ? (
                        <span className="text-muted-foreground text-xs">Not on a subject</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {(c.roles ?? []).map((r) => (
                            <Badge key={r} variant="secondary">
                              {r}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {(c.phones as { e164: string }[]).map((ph) => (
                        <p key={ph.e164}>{ph.e164}</p>
                      ))}
                    </TableCell>
                    <TableCell>
                      {c.emails.map((e) => (
                        <p key={e}>{e}</p>
                      ))}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{c.tz ?? "—"}</TableCell>
                    <TableCell>
                      {Object.keys(c.opt_out ?? {}).map((ch) => (
                        <span
                          key={ch}
                          className="bg-destructive/10 text-destructive mr-1 rounded-full px-2 py-0.5 text-xs"
                        >
                          {ch}
                        </span>
                      ))}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Edit ${c.name}`}
                        onClick={() => setEditing(c)}
                      >
                        <PencilIcon />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination page={p.page} limit={p.limit} total={p.total} onPage={setPage} />
          </>
        )}
      </QueryState>
      {editing && (
        <ContactDialog
          firmId={firmId}
          contact={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ContactDialog({
  firmId,
  contact,
  onClose,
}: {
  firmId: string;
  contact?: ContactPointOut;
  onClose: () => void;
}) {
  const form = useForm<ContactForm>({
    defaultValues: contact ? contactToForm(contact) : blankContact,
  });
  const options = {
    onSuccess: onClose,
    onError: (e: unknown) => showFormErrors(form.setError, e),
  };
  const feedback = { stale: STALE.subject, success: "Contact saved", error: false as const };
  const create = useApiMutation({ ...createContactPointMutation(), ...options }, feedback);
  const update = useApiMutation({ ...updateContactPointMutation(), ...options }, feedback);
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent>
        <FormProvider {...form}>
          <form
            onSubmit={form.handleSubmit((v) => {
              const body = contactBody(v);
              if (contact) update.mutate({ path: { contact_point_id: contact.id }, body });
              else create.mutate({ path: { firm_id: firmId }, body });
            })}
          >
            <DialogHeader>
              <DialogTitle>{contact ? `Edit ${contact.name}` : "New contact"}</DialogTitle>
            </DialogHeader>
            <div className="mt-4">
              <ContactFields />
            </div>
            <DialogFooter className="mt-4">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending || update.isPending}>
                Save contact
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
}
