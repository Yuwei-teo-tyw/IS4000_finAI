import { useEffect } from "react";
import InboxList, { type InboxRow } from "../../components/inbox/InboxList";
import { arcApi, bookToClient } from "../../services/arcApi";
import { useAsync } from "../../components/ui";
import { loadReturned, sendIpsToPm, useAllIpsReturned, useAllIpsSent } from "../../services/workflowStore";
import { useAllPackHandovers } from "../../services/packHandover";
import { usePackStates } from "../rm/generatedPackStore";
import { setActiveClientId } from "../../layouts/navConfig";

const IPS_KIND = "IPS SAA request";
const isOnboarding = (kind?: string) => /^onboarding/i.test(kind ?? "") || kind === IPS_KIND;

async function allClients() {
  const mock = await arcApi.listClients();
  try {
    const ids = new Set(mock.map((c) => c.id));
    return [...mock, ...(await arcApi.listBook()).clients.filter((b) => !ids.has(b.id)).map(bookToClient)];
  } catch { return mock; }
}

export default function PmInbox() {
  /** Mock clients plus every client in the backend book (e.g. Jane Fraser is "jft" there, "jfr" in the mock); the book is the source of truth, so a send for a book-only client must still resolve. */
  const clients = useAsync(allClients);
  const seeded = useAsync(() => arcApi.getInbox("pm"));
  const handovers = useAllPackHandovers();
  const localSent = useAllIpsSent();
  /** The backend is the source of truth for what the RM sent (IS-101); the browser flag alone misses sends made from another browser or session. */
  const backendSent = useAsync(async () => {
    const list = await allClients();
    const st = await Promise.all(list.map((c) => arcApi.getIpsSendStatus(c.id).then((s) => (s.sent ? c.id : null), () => null)));
    return st.filter((x): x is string => !!x);
  });
  /** An IPS SAA request only exists while the client is still onboarding; a client already in Monitoring has finished that workflow (no duplicate row). */
  const returned = loadReturned();
  /** Onboarding clients stay open; a client the RM already activated to Monitoring still lists here when its request was returned (Completed). */
  const ipsSent = [...new Set([...localSent, ...(backendSent ?? [])])].filter((id) => { const st = clients?.find((c) => c.id === id)?.status; return st === "Onboarding Phase" || returned.includes(id); });
  useEffect(() => { (backendSent ?? []).forEach((id) => { if (!localSent.includes(id)) sendIpsToPm(id); }); }, [backendSent, localSent]);
  useAllIpsReturned();
  const packStates = usePackStates();
  /** Live-first: an IPS request exists for every client whose IPS the RM sent; a quarterly review request for every pack the RM sent. Seeds only add priority. */
  const all: InboxRow[] | null = clients && seeded
    ? [
        ...ipsSent.flatMap((id) => {
          const c = clients.find((x) => x.id === id);
          const seed = seeded.find((x) => x.clientId === id && isOnboarding(x.kind));
          return c ? [{ id: `ips-${id}`, clientId: id, clientName: c.name, priority: seed?.priority ?? "normal" as const, nextMeeting: c.nextMeeting, kind: IPS_KIND, finished: returned.includes(id) }] : [];
        }),
        ...handovers.flatMap((f) => {
          const c = clients.find((x) => x.id === f.clientId);
          const seed = seeded.find((x) => x.clientId === f.clientId && !isOnboarding(x.kind));
          return c ? [{ id: `rev-${f.clientId}`, clientId: f.clientId, clientName: c.name, priority: seed?.priority ?? "normal" as const, nextMeeting: c.nextMeeting, kind: seed?.kind ?? "Quarterly review" }] : [];
        }),
        // Quarterly review packs the PM already sent back to the RM.
        ...Object.keys(packStates).filter((id) => packStates[id]?.handover?.status === "returned_to_rm" && !handovers.some((f) => f.clientId === id)).flatMap((id) => {
          const c = clients.find((x) => x.id === id);
          return c ? [{ id: `rev-${id}`, clientId: id, clientName: c.name, priority: "normal" as const, nextMeeting: c.nextMeeting, kind: "Quarterly review", finished: true }] : [];
        }),
        // Other seeded requests (not onboarding, not already covered by a live review row).
        ...seeded.filter((x) => !isOnboarding(x.kind) && !handovers.some((f) => f.clientId === x.clientId)).flatMap((x) => {
          const c = clients.find((y) => y.id === x.clientId);
          return [{ id: x.id, clientId: x.clientId, clientName: x.clientName, priority: x.priority, nextMeeting: c?.nextMeeting ?? x.receivedAt, kind: x.kind }];
        }),
      ]
    : null;
  const items = all ? all.filter((i) => !i.finished) : null;
  const completed = all ? all.filter((i) => i.finished) : undefined;
  return (
    <InboxList items={items} completed={completed} eyebrow="Portfolio Manager" title="Your inbox"
      welcomeRole="pm" listTitle="Requests" kindColumn
      openTo={(i) => (i.kind === IPS_KIND ? `/pm/requests/${i.clientId}/ips` : `/pm/cases/${i.clientId}/review`)}
      onOpen={(i) => setActiveClientId(i.clientId)}
      openedNote="Waiting for PM" highNote="Do these first" />
  );
}
