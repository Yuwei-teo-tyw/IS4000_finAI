import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Eye } from "lucide-react";
import { Badge, Card, GateChip, Loading, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { SortByDate, type SortOrder } from "../../components/documents/SortByDate";
import { arcApi } from "../../services/arcApi";
import type { HouseView, Product } from "../../types/arc";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { setActiveClientId, useActiveClientId } from "../../layouts/navConfig";
import { Button } from "../../components/ui";
import ClientOverview from "../client/ClientOverview";
import { IpsHistory } from "../client/IpsHistory";
import { ClientParamProvider } from "../../components/ps/EmbeddedClient";
import { toggleSelection, useSelection } from "../../services/workflowStore";
import { ClientStrip, PS_STEPS } from "./psShared";

const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300";

function RecordCard({ r }: { r: HouseView }) {
  const [preview, setPreview] = useState(false);
  return (
    <Card className="!p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xl">House View {r.month}</h3>
        <Badge tone={r.file ? "green" : "grey"}>{r.file ? "Available" : "Placeholder"}</Badge>
      </div>
      <p className="mt-2 text-sm text-ink-muted">Issued {r.issuedOn} · Author: {r.author}</p>
      <div className="mt-6">
        <button type="button" aria-label="Preview" title="Preview" onClick={() => setPreview(true)} className={iconBtn}><Eye size={18} /></button>
      </div>
      {preview && (
        <DocumentPreviewModal title={`House View ${r.month}`} onClose={() => setPreview(false)}>
          {r.file ? (
            <iframe src={r.file} title={`House View ${r.month}`} className="h-[70vh] w-full border border-hairline bg-surface-100" />
          ) : (
            <div className="border border-hairline bg-surface-100 p-16 text-center">
              <p className="text-xl">House View {r.month}</p>
              <p className="mt-3 text-base text-ink-muted">Not uploaded yet.</p>
            </div>
          )}
        </DocumentPreviewModal>
      )}
    </Card>
  );
}

function ProductShelf({ products, limit, clientId }: { products: Product[]; limit: number; clientId: string }) {
  const selected = useSelection(clientId);
  const [cls, setCls] = useState<string>("All");
  const classes = ["All", ...Array.from(new Set(products.map((p) => p.assetClass)))];
  const rows = cls === "All" ? products : products.filter((p) => p.assetClass === cls);
  return (
    <Section title="Product shelf" hint="Fees are for information only.">
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
              <label className="flex min-w-0 cursor-pointer items-start gap-3">
                <input type="checkbox" className="mt-1.5 h-5 w-5 cursor-pointer" checked={selected.some((r) => r.product === p.name)} aria-label={`Select ${p.name}`}
                  onChange={() => toggleSelection(clientId, { assetClass: p.assetClass, product: p.name, industryFocus: p.suitability || p.whyBuy, top5: [], confidencePct: Math.min(95, 50 + p.stars * 9), ranking: [] })} />
                <h3 className="min-w-0 text-xl">{p.name}</h3>
              </label>
              <Badge tone={p.riskRating > limit ? "amber" : "green"}>Risk {p.riskRating} of 5</Badge>
            </div>
            <p className="mt-1 text-xs text-ink-500">{p.id} · {p.assetClass}</p>
            <p className="mt-4 text-base leading-relaxed text-ink-700">{p.whyBuy}</p>
            <p className="mt-3 text-sm text-ink-500">{p.suitability}</p>
            <p className="mt-5 text-sm text-ink-700">Fee {p.feePct.toFixed(2)}%{p.riskRating > limit ? " · above this client's risk limit" : ""}</p>
          </Card>
        ))}
      </div>
      {selected.length > 0 && (
        <div className="sticky bottom-0 z-10 mt-10 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-hairline bg-surface-100 px-7 py-5">
          <p className="text-base text-ink-700">{selected.length} product{selected.length === 1 ? "" : "s"} ticked</p>
          <Button to={`/ps/cases/${clientId}/finalise`}>Finalise list ({selected.length})</Button>
        </div>
      )}
    </Section>
  );
}

export default function MarketResearch() {
  const [params, setParams] = useSearchParams();
  const clientId = useActiveClientId();
  const urlClient = params.get("client");
  useEffect(() => { if (urlClient) setActiveClientId(urlClient); }, [urlClient]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const products = useAsync(() => arcApi.getProducts(clientId), [clientId]);
  const records = useAsync(() => arcApi.getHouseViews(clientId), [clientId]);
  type Tab = "research" | "records" | "shelf" | "client360" | "ips";
  const rawTab = params.get("tab");
  const tab: Tab = (["research", "records", "shelf", "client360", "ips"] as const).find((t) => t === rawTab) ?? "research";
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); if (t === "research") n.delete("tab"); else n.set("tab", t); return n; }, { replace: true });
  const [order, setOrder] = useState<SortOrder>("latest");
  const sorted = useMemo(
    () => [...(records ?? [])].sort((a, b) => (order === "latest" ? b.issuedOn.localeCompare(a.issuedOn) : a.issuedOn.localeCompare(b.issuedOn))),
    [records, order],
  );

  if (!products || !records) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Product Specialist" title="AI Assistant"
        actions={
          <GateChip id="G3" state="not_started" />
        } />
      <Stepper steps={PS_STEPS} current={0} />
      <ClientStrip client={client} />

      <div role="tablist" className="mb-10 flex gap-8 border-b border-hairline">
        {([["research", "AI Assistant"], ["records", "House View Records"], ["shelf", "Product Shelf"], ["client360", "Client 360"], ["ips", "Client IPS"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px cursor-pointer border-b-2 pb-3 text-base ${tab === k ? "border-brand font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>

      <div hidden={tab !== "research"}><GenevaChat key={clientId} role="ps" clientId={clientId} /></div>
      {tab === "records" && (
        <div>
      <Section title="House view records" hint="Past monthly house views.">
        <div className="mb-6 flex justify-end"><SortByDate value={order} onChange={setOrder} /></div>
        <div className="flex flex-col gap-8">{sorted.map((r) => <RecordCard key={r.id} r={r} />)}</div>
      </Section>

        </div>
      )}
      {tab === "shelf" && <ProductShelf products={products} limit={client?.riskCap ?? 3} clientId={clientId} />}
      {tab === "client360" && <ClientParamProvider clientId={clientId}><ClientOverview /></ClientParamProvider>}
      {tab === "ips" && <Section title="Client IPS"><IpsHistory clientId={clientId} clientName={client?.name} /></Section>}
    </div>
  );
}
