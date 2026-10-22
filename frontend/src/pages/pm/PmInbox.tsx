import InboxList, { type InboxRow } from "../../components/inbox/InboxList";
import { arcApi } from "../../services/arcApi";
import { useAsync } from "../../components/ui";
import { loadReturned, useAllFinalised, useAllIpsReturned, useAllIpsSent } from "../../services/workflowStore";
import { setActiveClientId } from "../../layouts/navConfig";

const IPS_KIND = "IPS SAA request";
const isOnboarding = (kind?: string) => /^onboarding/i.test(kind ?? "") || kind === IPS_KIND;

export default function PmInbox() {
  const clients = useAsync(() => arcApi.listClients());
  const seeded = useAsync(() => arcApi.getInbox("pm"));
  const finalised = useAllFinalised();
  const ipsSent = useAllIpsSent();
  useAllIpsReturned();
  const returned = loadReturned();
  /** Live-first: an IPS request exists for every client whose IPS the RM sent; a review request for every PS-finalised list. Seeds only add priority. */
  const items: InboxRow[] | null = clients && seeded
    ? [
        ...ipsSent.flatMap((id) => {
          const c = clients.find((x) => x.id === id);
          const seed = seeded.find((x) => x.clientId === id && isOnboarding(x.kind));
          return c ? [{ id: `ips-${id}`, clientId: id, clientName: c.name, priority: seed?.priority ?? "normal" as const, nextMeeting: c.nextMeeting, kind: IPS_KIND, finished: returned.includes(id) }] : [];
        }),
        ...finalised.flatMap((f) => {
          const c = clients.find((x) => x.id === f.clientId);
          const seed = seeded.find((x) => x.clientId === f.clientId && !isOnboarding(x.kind));
          return c ? [{ id: `rev-${f.clientId}`, clientId: f.clientId, clientName: c.name, priority: seed?.priority ?? "normal" as const, nextMeeting: c.nextMeeting, kind: seed?.kind ?? "Quarterly review" }] : [];
        }),
        // Other seeded requests (not onboarding, not already covered by a live review row).
        ...seeded.filter((x) => !isOnboarding(x.kind) && !finalised.some((f) => f.clientId === x.clientId)).flatMap((x) => {
          const c = clients.find((y) => y.id === x.clientId);
          return [{ id: x.id, clientId: x.clientId, clientName: x.clientName, priority: x.priority, nextMeeting: c?.nextMeeting ?? x.receivedAt, kind: x.kind }];
        }),
      ]
    : null;
  return (
    <InboxList items={items} eyebrow="Portfolio Manager" title="Your inbox"
      welcomeRole="pm" listTitle="Requests" kindColumn
      openTo={(i) => (i.kind === IPS_KIND ? `/pm/requests/${i.clientId}/3l` : `/pm/cases/${i.clientId}/products`)}
      onOpen={(i) => setActiveClientId(i.clientId)}
      openedNote="Waiting for PM" highNote="Do these first" />
  );
}
