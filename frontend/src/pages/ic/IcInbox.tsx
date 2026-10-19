import InboxList, { type InboxRow } from "../../components/inbox/InboxList";
import { arcApi } from "../../services/arcApi";
import { useAsync } from "../../components/ui";
import { useAllFinalised } from "../../services/workflowStore";
import { setActiveClientId } from "../../layouts/navConfig";

const isOnboarding = (kind?: string) => /^onboarding/i.test(kind ?? "");

export default function IcInbox() {
  const clients = useAsync(() => arcApi.listClients());
  const seeded = useAsync(() => arcApi.getInbox("ic"));
  const finalised = useAllFinalised();
  const items: InboxRow[] | null = clients && seeded
    ? [
        ...seeded.flatMap((s) => {
          const c = clients.find((x) => x.id === s.clientId);
          return [{ id: s.id, clientId: s.clientId, clientName: s.clientName, priority: s.priority, nextMeeting: c?.nextMeeting ?? s.receivedAt, kind: s.kind }];
        }),
        // Live workflow state: a PS-finalised list for a client not already seeded appears as its own row.
        ...finalised.flatMap((f) => {
          const c = clients.find((x) => x.id === f.clientId);
          return c && !seeded.some((s) => s.clientId === f.clientId)
            ? [{ id: c.id, clientId: c.id, clientName: c.name, priority: "normal" as const, nextMeeting: c.nextMeeting, kind: "Quarterly review" }]
            : [];
        }),
      ]
    : null;
  return (
    <InboxList items={items} eyebrow="Investment Counsellor" title="Your inbox"
      listTitle="Requests"
      openTo={(i) => (isOnboarding(i.kind) ? `/ic/requests/${i.clientId}/3l` : `/ic/cases/${i.clientId}/products`)}
      onOpen={(i) => setActiveClientId(i.clientId)}
      openedNote="Waiting for IC" highNote="Do these first" />
  );
}
