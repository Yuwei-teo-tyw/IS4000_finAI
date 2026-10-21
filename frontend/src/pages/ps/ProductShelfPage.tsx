import { useState } from "react";
import { Badge, Card, Loading, PageHeader, Section, useAsync, useAsyncResult } from "../../components/ui";
import { arcApi, ProductRecommenderError } from "../../services/arcApi";
import type { Product } from "../../types/arc";
import { useActiveClientId } from "../../layouts/navConfig";
import { ClientStrip } from "./psShared";

function ProductShelf({ products, limit }: { products: Product[]; limit: number }) {
  const [cls, setCls] = useState<string>("All");
  const classes = ["All", ...Array.from(new Set(products.map((p) => p.assetClass)))];
  const rows = cls === "All" ? products : products.filter((p) => p.assetClass === cls);
  return (
    <Section title="Product shelf" hint="Browse only. Fees are for information only and never used to rank. To finalise, tell the assistant which products you are happy with.">
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
            <p className="mt-5 text-sm text-ink-700">{p.feePct === null ? "Fee not available" : `Fee ${p.feePct.toFixed(2)}%`}{p.riskRating > limit ? " · above this client's risk limit" : ""}</p>
          </Card>
        ))}
      </div>
    </Section>
  );
}

export default function ProductShelfPage() {
  const clientId = useActiveClientId();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const { data: products, error } = useAsyncResult(() => arcApi.getProducts(clientId), [clientId]);
  return (
    <div>
      <PageHeader eyebrow="Product Specialist" title="Product Shelf" />
      <ClientStrip client={client} />
      {error ? (
        <Card className="!p-8">
          <h2 className="text-xl">The product shelf is unavailable</h2>
          <p className="mt-3 text-base text-ink-700">{error.message}</p>
          {error instanceof ProductRecommenderError && error.details.map((d) => <p key={d} className="mt-2 text-sm text-ink-muted">{d}</p>)}
        </Card>
      ) : !products ? <Loading /> : <ProductShelf products={products} limit={client?.riskCap ?? 3} />}
    </div>
  );
}
