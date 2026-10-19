import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Card, GateChip, Loading, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import type { Product } from "../../types/arc";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { setActiveClientId, useActiveClientId } from "../../layouts/navConfig";
import { ClientStrip, PS_STEPS } from "./psShared";

function ProductShelf({ products, limit }: { products: Product[]; limit: number }) {
  const [cls, setCls] = useState<string>("All");
  const classes = ["All", ...Array.from(new Set(products.map((p) => p.assetClass)))];
  const rows = cls === "All" ? products : products.filter((p) => p.assetClass === cls);
  return (
    <Section title="Product shelf" hint="Every product available for this client. Fees are shown for information and never used to rank.">
      <div className="mb-8 flex flex-wrap gap-3">
        {classes.map((c) => (
          <button key={c} type="button" onClick={() => setCls(c)}
            className={`cursor-pointer rounded-full px-5 py-2 text-sm font-semibold ${cls === c ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>
            {c} ({c === "All" ? products.length : products.filter((p) => p.assetClass === c).length})
          </button>
        ))}
      </div>
      <div className="grid gap-8 md:grid-cols-2">
        {rows.map((p) => (
          <Card key={p.id} className="!p-8">
            <div className="flex items-start justify-between gap-3">
              <h3 className="min-w-0 text-xl">{p.name}</h3>
              <Badge tone={p.riskRating > limit ? "amber" : "green"}>Risk {p.riskRating} of 5</Badge>
            </div>
            <p className="mt-1 text-xs text-ink-500">{p.id} · {p.assetClass}</p>
            <p className="mt-4 text-base leading-relaxed text-ink-700">{p.whyBuy}</p>
            <p className="mt-3 text-sm text-ink-500">{p.suitability}</p>
            <p className="mt-5 text-sm text-ink-700">Fee {p.feePct.toFixed(2)}%{p.riskRating > limit ? " · above this client's risk limit" : ""}</p>
          </Card>
        ))}
      </div>
    </Section>
  );
}

export default function MarketResearch() {
  const [params] = useSearchParams();
  const stored = useActiveClientId();
  const [clientId, setClientId] = useState(params.get("client") ?? stored);
  const clients = useAsync(() => arcApi.listClients());
  const change = (id: string) => { setActiveClientId(id); setClientId(id); };
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const products = useAsync(() => arcApi.getProducts(clientId), [clientId]);
  const [tab, setTab] = useState<"research" | "shelf">("research");

  if (!products) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Product Specialist" title="AI Assistant" subtitle="Research the market and shortlist products for the selected client."
        actions={
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-3 text-sm text-ink-muted">
              Client
              <select value={clientId} onChange={(e) => change(e.target.value)} className="rounded-sm border border-hairline-strong bg-surface-100 px-4 py-2.5 text-[15px] text-ink">
                {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <GateChip id="G3" state="not_started" />
          </div>
        } />
      <Stepper steps={PS_STEPS} current={0} />
      <ClientStrip client={client} />

      <div role="tablist" className="mb-10 flex gap-8 border-b border-hairline">
        {([["research", "AI Assistant"], ["shelf", "Product Shelf"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px cursor-pointer border-b-2 pb-3 text-base ${tab === k ? "border-brand font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>

      <div hidden={tab !== "research"}><GenevaChat key={clientId} role="ps" clientId={clientId} /></div>
      {tab === "shelf" && <ProductShelf products={products} limit={client?.riskCap ?? 3} />}
    </div>
  );
}
