import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, Loading, PageHeader, Stat, useAsync } from "../../components/ui";

const triggerLabel = { 1: "Trigger 1 · Onboarding", 2: "Trigger 2 · Life event", 3: "Trigger 3 · Quarterly review" } as const;

export default function IcInbox() {
  const items = useAsync(() => arcApi.getInbox("ic"));
  if (!items) return <Loading />;
  const high = items.filter((i) => i.priority === "high").length;

  return (
    <div>
      <PageHeader eyebrow="Investment Counsellor" title="Your inbox" subtitle="Requests waiting for you. Open one to start; each opens its own guided steps." />
      <div className="mb-12 grid gap-8 sm:grid-cols-2">
        <Stat label="Open requests" value={items.length} note="Waiting for IC" />
        <Stat label="High priority" value={high} note="Do these first" />
      </div>
      <div className="flex flex-col gap-8">
        {items.map((i) => (
          <Card key={i.id} accent className="flex flex-col gap-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-2xl">{i.clientName}</h2>
                <p className="mt-1 text-sm text-ink-500">{i.kind} · from {i.from.toUpperCase()} · {i.receivedAt}</p>
              </div>
              <div className="flex gap-2">
                {i.priority === "high" && <Badge tone="amber">High priority</Badge>}
                <Badge tone="sky">{triggerLabel[i.trigger]}</Badge>
              </div>
            </div>
            <p className="max-w-2xl text-base text-ink-700">{i.summary}</p>
            <div>
              <Button to={i.trigger === 3 ? `/ic/cases/${i.clientId}/insights` : `/ic/requests/${i.clientId}/3l`}>Open request</Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
