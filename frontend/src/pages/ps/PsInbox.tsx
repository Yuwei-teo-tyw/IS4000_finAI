import InboxList, { type InboxRow } from "../../components/inbox/InboxList";
import { arcApi } from "../../services/arcApi";
import { useAsync } from "../../components/ui";
import { useAllFinalised, useReviewRequests } from "../../services/workflowStore";
import { setActiveClientId } from "../../layouts/navConfig";

export default function PsInbox() {
  const clients = useAsync(() => arcApi.listClients());
  const requests = useReviewRequests();
  const finalised = useAllFinalised();
  const seeded = useAsync(() => arcApi.getInbox("ps"));
  const items: InboxRow[] | null = clients && seeded
    ? [
        ...seeded.flatMap((i) => {
          const c = clients.find((x) => x.id === i.clientId);
          const live = requests.find((r) => r.clientId === i.clientId);
          return [{ id: i.id, clientId: i.clientId, clientName: c?.name ?? i.clientName, priority: live?.priority ?? i.priority, nextMeeting: c?.nextMeeting ?? "", kind: i.kind, finished: finalised.some((f) => f.clientId === i.clientId) }];
        }),
        ...requests.filter((r) => !seeded.some((i) => i.clientId === r.clientId)).flatMap((r) => {
          const c = clients.find((x) => x.id === r.clientId);
          return c ? [{ id: c.id, clientId: c.id, clientName: c.name, priority: r.priority, nextMeeting: c.nextMeeting, finished: finalised.some((f) => f.clientId === c.id) }] : [];
        }),
      ]
    : null;
  return (
    <InboxList items={items} eyebrow="Product Specialist" title="Inbox"
      welcomeRole="ps" listTitle="Requests" openTo={(i) => `/ps/assistant?client=${i.clientId}`} onOpen={(i) => setActiveClientId(i.clientId)}
      showFilter finishedLabel="Sent to PM"
      openedNote="Waiting for product review" highNote="Due before the client meeting" />
  );
}
