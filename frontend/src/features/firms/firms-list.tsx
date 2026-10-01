import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { PlusIcon } from "lucide-react";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import type { z } from "zod";

import { createFirmMutation, listFirmsOptions } from "@/api/generated/@tanstack/react-query.gen";
import { Avatar } from "@/components/shared/avatar";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Pagination } from "@/components/shared/pagination";
import { QueryState } from "@/components/shared/query-state";
import { SearchInput } from "@/components/shared/search-input";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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

import { FirmFields } from "./firm-fields";
import { FIRM_COLORS, newFirmSchema, slugify } from "./model";

export function FirmsList({
  q,
  page,
  onSearch,
}: {
  q?: string;
  page: number;
  onSearch: (s: { q?: string; page?: number }) => void;
}) {
  const [creating, setCreating] = useState(false);
  const firms = useQuery({
    ...listFirmsOptions({ query: { q, page, limit: 20 } }),
    placeholderData: keepPreviousData,
  });
  const add = (
    <Button onClick={() => setCreating(true)}>
      <PlusIcon /> New firm
    </Button>
  );
  return (
    <>
      <PageHeader
        title="Firms"
        description="The organisations agents work for. Each firm connects its own mailbox, Slack and phone number."
        actions={add}
      />
      <div className="mb-4">
        <SearchInput
          label="Search firms"
          placeholder="Search name or slug"
          value={q}
          onCommit={(next) => onSearch({ q: next, page: 1 })}
        />
      </div>
      <QueryState
        query={firms}
        what="Firms"
        isEmpty={(p) => p.total === 0}
        empty={
          q ? (
            <EmptyState title="No firms match" />
          ) : (
            <EmptyState
              title="No firms yet"
              description="Add the first firm to map agents to it."
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
                  <TableHead>Firm</TableHead>
                  <TableHead>Timezone</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.items.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar label={f.name} color={f.color} />
                        <div>
                          <Link
                            to="/firms/$firmId"
                            params={{ firmId: f.id }}
                            search={{ tab: "overview" }}
                            className="font-medium hover:underline"
                          >
                            {f.name}
                          </Link>
                          <p className="text-muted-foreground font-mono text-xs">{f.slug}</p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{f.timezone}</TableCell>
                    <TableCell>
                      <StatusBadge status={f.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination
              page={p.page}
              limit={p.limit}
              total={p.total}
              onPage={(n) => onSearch({ page: n })}
            />
          </>
        )}
      </QueryState>
      {creating && <NewFirmDialog onClose={() => setCreating(false)} />}
    </>
  );
}

function NewFirmDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [slugEdited, setSlugEdited] = useState(false);
  const form = useForm<z.infer<typeof newFirmSchema>>({
    resolver: zodResolver(newFirmSchema),
    defaultValues: {
      name: "",
      slug: "",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      color: FIRM_COLORS[0],
    },
  });
  const create = useApiMutation(
    {
      ...createFirmMutation(),
      onSuccess: (firm) =>
        void navigate({
          to: "/firms/$firmId",
          params: { firmId: firm.id },
          search: { tab: "connections" },
        }),
      onError: (e) => showFormErrors(form.setError, e),
    },
    // A new firm also gets an @orchestrator mapping.
    {
      stale: [...STALE.firm, ...STALE.mapping],
      success: (firm) => `Added ${firm.name}`,
      error: false,
    },
  );
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(open) => open || onClose()}>
      <DialogContent>
        <FormProvider {...form}>
          <form onSubmit={form.handleSubmit((body) => create.mutate({ body }))}>
            <DialogHeader>
              <DialogTitle>New firm</DialogTitle>
            </DialogHeader>
            <div className="mt-4 space-y-4">
              <FirmFields
                onNameChange={(name) => {
                  if (!slugEdited) form.setValue("slug", slugify(name));
                }}
              />
              <Field data-invalid={!!errors.slug}>
                <FieldLabel htmlFor="firm-slug">Slug</FieldLabel>
                <Input
                  id="firm-slug"
                  className="font-mono"
                  {...form.register("slug", { onChange: () => setSlugEdited(true) })}
                />
                <FieldDescription>Permanent short name. It can't change later.</FieldDescription>
                <FieldError errors={[errors.slug]} />
              </Field>
              {errors.root && (
                <p role="alert" className="text-destructive text-sm">
                  {errors.root.message}
                </p>
              )}
            </div>
            <DialogFooter className="mt-6">
              <Button type="submit" disabled={create.isPending}>
                Add firm
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
}
