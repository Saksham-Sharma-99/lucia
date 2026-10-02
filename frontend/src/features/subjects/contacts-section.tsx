import { MailIcon, PhoneIcon, PlusIcon, XIcon } from "lucide-react";
import { useState } from "react";

import {
  unlinkSubjectContactMutation,
  updateContactPointMutation,
  updateSubjectContactMutation,
} from "@/api/generated/@tanstack/react-query.gen";
import type { SubjectContactOut, SubjectDetail } from "@/api/generated/types.gen";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { STALE } from "@/lib/invalidate";
import { useApiMutation } from "@/lib/use-api-mutation";
import { cn } from "@/lib/utils";

import { AddContactDialog } from "./add-contact-dialog";

const CONSENT = ["granted", "refused", "unknown"] as const;
type Consent = (typeof CONSENT)[number];

/** The people on a subject: how to reach them, what they agreed to, and opt-outs. */
export function ContactsSection({
  firmId,
  subject,
  readOnly,
}: {
  firmId: string;
  subject: SubjectDetail;
  readOnly?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Contacts</h3>
        {!readOnly && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <PlusIcon /> Add contact
          </Button>
        )}
      </div>
      {subject.contacts.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No contacts yet. Agents can only reach people listed here.
        </p>
      ) : (
        <ul className="space-y-2">
          {subject.contacts.map((link) => (
            <ContactCard key={link.id} link={link} readOnly={readOnly} />
          ))}
        </ul>
      )}
      {adding && (
        <AddContactDialog
          firmId={firmId}
          subjectId={subject.id}
          linked={subject.contacts.map((c) => c.contact_point.id)}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  );
}

function ContactCard({ link, readOnly }: { link: SubjectContactOut; readOnly?: boolean }) {
  const cp = link.contact_point;
  const [removing, setRemoving] = useState(false);
  const [clearing, setClearing] = useState<string | null>(null);
  const optedOut = Object.keys(cp.opt_out ?? {});
  const unlink = useApiMutation(unlinkSubjectContactMutation(), {
    stale: STALE.subject,
    success: `Removed ${cp.name}`,
  });
  return (
    <li className="bg-card space-y-3 rounded-lg border p-3 text-sm">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{cp.name}</p>
          <p className="text-muted-foreground text-xs">
            <Badge variant="secondary" className="mr-1.5">
              {link.role}
            </Badge>
            {cp.tz ?? "No timezone"}
          </p>
        </div>
        {!readOnly && (
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={`Remove ${cp.name}`}
            onClick={() => setRemoving(true)}
          >
            <XIcon />
          </Button>
        )}
      </div>
      <div className="text-muted-foreground space-y-1">
        {(cp.phones as { e164: string; type?: string }[]).map((p) => (
          <p key={p.e164} className="flex items-center gap-1.5">
            <PhoneIcon className="size-3.5" />
            <span className="text-foreground font-mono">{p.e164}</span>
            {p.type && p.type !== "voice" && <span>({p.type})</span>}
          </p>
        ))}
        {cp.emails.map((e) => (
          <p key={e} className="flex items-center gap-1.5">
            <MailIcon className="size-3.5" />
            <span className="text-foreground">{e}</span>
          </p>
        ))}
      </div>
      <div className="space-y-1.5">
        {(["voice", "email"] as const).map((channel) => (
          <ConsentControl key={channel} link={link} channel={channel} readOnly={readOnly} />
        ))}
      </div>
      {optedOut.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {optedOut.map((channel) => (
            <span
              key={channel}
              className="bg-destructive/10 text-destructive inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
            >
              Opted out: {channel}
              {!readOnly && (
                <button
                  type="button"
                  aria-label={`Clear ${channel} opt-out`}
                  className="hover:text-foreground"
                  onClick={() => setClearing(channel)}
                >
                  <XIcon className="size-3" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title={`Remove ${cp.name} from this subject?`}
        description="The contact stays in the firm's contacts and on any other subjects."
        confirmLabel="Remove"
        destructive
        onConfirm={() => unlink.mutate({ path: { link_id: link.id } })}
      />
      {clearing && (
        <ClearOptOut
          contactPointId={cp.id}
          channel={clearing}
          remaining={optedOut.filter((c) => c !== clearing)}
          onClose={() => setClearing(null)}
        />
      )}
    </li>
  );
}

function ConsentControl({
  link,
  channel,
  readOnly,
}: {
  link: SubjectContactOut;
  channel: "voice" | "email";
  readOnly?: boolean;
}) {
  const current =
    ((link.consent?.[channel] as { status?: Consent } | undefined)?.status as Consent) ?? "unknown";
  const save = useApiMutation(updateSubjectContactMutation(), {
    stale: STALE.subject,
  });
  const label = channel === "voice" ? "Voice" : "Email";
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground w-24 text-xs">{label} consent</span>
      <div
        role="radiogroup"
        aria-label={`${label} consent`}
        className="inline-flex rounded-md border p-0.5"
      >
        {CONSENT.map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={current === value}
            aria-label={`${label} consent: ${value}`}
            disabled={readOnly || save.isPending}
            onClick={() =>
              current !== value &&
              save.mutate({ path: { link_id: link.id }, body: { consent: { [channel]: value } } })
            }
            className={cn(
              "rounded px-2 py-0.5 text-xs capitalize disabled:cursor-default",
              current === value
                ? value === "granted"
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                  : value === "refused"
                    ? "bg-destructive/15 text-destructive"
                    : "bg-muted text-foreground"
                : "text-muted-foreground",
            )}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}

function ClearOptOut({
  contactPointId,
  channel,
  remaining,
  onClose,
}: {
  contactPointId: string;
  channel: string;
  remaining: string[];
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const clear = useApiMutation(
    { ...updateContactPointMutation(), onSuccess: onClose },
    { stale: STALE.subject, success: `${channel} opt-out cleared` },
  );
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => open || onClose()}
      title={`Clear the ${channel} opt-out?`}
      description={
        <div className="space-y-2">
          <p>
            Agents may contact this person by {channel} again. The reason is kept in the audit log.
          </p>
          <Label htmlFor="opt-out-reason">Reason</Label>
          <Textarea
            id="opt-out-reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="At least 10 characters"
          />
        </div>
      }
      confirmLabel="Clear opt-out"
      confirmDisabled={reason.trim().length < 10 || clear.isPending}
      onConfirm={() =>
        clear.mutate({
          path: { contact_point_id: contactPointId },
          body: {
            opt_out: remaining as ("voice" | "email" | "slack")[],
            reason: reason.trim(),
          },
        })
      }
    />
  );
}
