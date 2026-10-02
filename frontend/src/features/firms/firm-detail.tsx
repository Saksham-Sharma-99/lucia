import { useQuery } from "@tanstack/react-query";

import { getFirmOptions } from "@/api/generated/@tanstack/react-query.gen";
import { Avatar } from "@/components/shared/avatar";
import { QueryState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ContactsTab } from "@/features/subjects/contacts-tab";
import { SubjectDrawer } from "@/features/subjects/subject-drawer";
import { SubjectsTab } from "@/features/subjects/subjects-tab";

import { ConnectionsTab } from "./connections/connections-tab";
import { FirmOverviewTab } from "./firm-overview-tab";
import { FirmSettingsTab } from "./firm-settings-tab";
import type { FirmTab } from "./model";

export function FirmDetailPage({
  firmId,
  tab,
  connected,
  onTab,
  onConnectedSeen,
  onSubject,
  subject,
  onSubjectClose,
}: {
  firmId: string;
  tab: FirmTab;
  /** Set by the OAuth callback redirect once a consent link was approved. */
  connected?: string;
  onTab: (t: FirmTab) => void;
  onConnectedSeen: () => void;
  /** Open a subject's drawer ("new" to create one). */
  onSubject: (subjectId: string) => void;
  subject?: string;
  onSubjectClose: () => void;
}) {
  const firm = useQuery(getFirmOptions({ path: { firm_id: firmId } }));
  return (
    <QueryState query={firm} what="This firm" loading={<Skeleton className="h-96 w-full" />}>
      {(f) => (
        <>
          <header className="mb-6 flex items-start gap-4">
            <Avatar label={f.name} color={f.color} size="lg" />
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-[1.375rem] leading-tight font-semibold tracking-tight">
                  {f.name}
                </h1>
                <StatusBadge status={f.status} />
              </div>
              <p className="text-muted-foreground text-sm">
                <span className="font-mono">{f.slug}</span> · {f.timezone}
              </p>
            </div>
          </header>
          <Tabs value={tab} onValueChange={(t) => onTab(t as FirmTab)}>
            <TabsList variant="line" className="mb-6">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="settings">Settings</TabsTrigger>
              <TabsTrigger value="connections">Connections</TabsTrigger>
              <TabsTrigger value="subjects">Subjects</TabsTrigger>
              <TabsTrigger value="contacts">Contacts</TabsTrigger>
            </TabsList>
            <TabsContent value="overview">
              <FirmOverviewTab firm={f} />
            </TabsContent>
            <TabsContent value="settings">
              <FirmSettingsTab firm={f} />
            </TabsContent>
            <TabsContent value="connections">
              <ConnectionsTab
                firmId={f.id}
                connected={connected}
                onConnectedSeen={onConnectedSeen}
              />
            </TabsContent>
            <TabsContent value="subjects">
              <SubjectsTab firmId={f.id} onOpen={onSubject} />
            </TabsContent>
            <TabsContent value="contacts">
              <ContactsTab firmId={f.id} />
            </TabsContent>
          </Tabs>
          {subject && (
            <SubjectDrawer
              firmId={f.id}
              subjectId={subject}
              onOpen={onSubject}
              onClose={onSubjectClose}
            />
          )}
        </>
      )}
    </QueryState>
  );
}
