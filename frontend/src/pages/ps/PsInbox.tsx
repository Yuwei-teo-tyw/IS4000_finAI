import { Clock } from "lucide-react";
import { Badge, Button, Card, Loading, PageHeader, Stat, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";

export default function PsInbox() {
  const items = useAsync(() => arcApi.getInbox("ps"));
  if (!items) return <Loading />;
  const high = items.filter((i) => i.priority === "high").length;
  return (
    <div>
      <PageHeader eyebrow="Product Specialist" title="Inbox" subtitle="Product-review requests from Relationship Managers. Open one to research the market and shortlist products." />
      <div className="mb-12 grid gap-6 md:grid-cols-3">
        <Stat label="Open requests" value={items.length} />
        <Stat label="High priority" value={high} note="Due before the client meeting" />
        <Stat label="Gate" value="G3" note="You approve the product list" />
      </div>
      <div className="flex flex-col gap-8">
        {items.map((it) => (
          <Card key={it.id} className="flex flex-wrap items-center justify-between gap-8 !p-8">
            <div className="max-w-2xl">
              <div className="mb-3 flex items-center gap-3">
                <Badge tone={it.priority === "high" ? "amber" : "grey"}>{it.priority === "high" ? "High priority" : "Normal"}</Badge>
                <span className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">{it.kind}</span>
              </div>
              <h3 className="text-2xl">{it.clientName}</h3>
              <p className="mt-2 text-base text-ink-700">{it.summary}</p>
              <p className="mt-4 flex items-center gap-2 text-sm text-ink-500"><Clock size={14} /> Received {it.receivedAt}</p>
            </div>
            <Button to={`/ps/assistant?client=${it.clientId}`}>Open request</Button>
          </Card>
        ))}
        {items.length === 0 && <Card><p className="text-ink-500">No requests waiting.</p></Card>}
      </div>
    </div>
  );
}
