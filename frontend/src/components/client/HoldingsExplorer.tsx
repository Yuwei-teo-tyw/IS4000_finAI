import { useEffect, useMemo, useState } from "react";
import { arcApi } from "../../services/arcApi";
import type { AssetClass, CorrelationMatrix, Holding } from "../../types/arc";
import { Loading } from "../ui";
import { HoldingsTable } from "./HoldingsTable";
import { CorrelationHeatmap } from "./CorrelationHeatmap";

const ORDER: AssetClass[] = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"];

export function HoldingsExplorer({ clientId }: { clientId: string }) {
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [corr, setCorr] = useState<CorrelationMatrix | null>(null);
  const [active, setActive] = useState<AssetClass | "All">("All");

  useEffect(() => {
    let live = true;
    setHoldings(null); setActive("All");
    arcApi.getHoldings(clientId).then((h) => live && setHoldings(h));
    arcApi.getCorrelation(clientId).then((c) => live && setCorr(c));
    return () => { live = false; };
  }, [clientId]);

  const classes = useMemo(() => ORDER.filter((c) => holdings?.some((h) => h.assetClass === c)), [holdings]);

  const sub = useMemo(() => {
    if (!corr || !holdings) return null;
    const idx = holdings.map((h, i) => (active === "All" || h.assetClass === active ? i : -1)).filter((i) => i >= 0 && i < corr.labels.length);
    return { labels: idx.map((i) => corr.labels[i]), matrix: idx.map((i) => idx.map((j) => corr.matrix[i][j])) };
  }, [corr, holdings, active]);

  if (!holdings) return <Loading />;

  const chip = (key: AssetClass | "All", count: number) => (
    <button key={key} type="button" aria-pressed={active === key} onClick={() => setActive(key)}
      className={`rounded-sm border px-4 py-2 text-sm transition-colors ${active === key ? "border-surface-inverse bg-surface-inverse text-ink-inverse" : "border-hairline bg-surface-100 text-ink hover:bg-surface-200"}`}>
      {key} <span className={active === key ? "opacity-70" : "text-ink-muted"}>{count}</span>
    </button>
  );

  return (
    <div className="space-y-16">
      <section className="space-y-6">
        <div>
          <h2 className="text-2xl font-light text-ink">Holdings</h2>
          <p className="mt-2 text-sm text-ink-muted">Filter by asset class to see what the client holds and how each position is performing.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          {chip("All", holdings.length)}
          {classes.map((c) => chip(c, holdings.filter((h) => h.assetClass === c).length))}
        </div>
        <HoldingsTable holdings={holdings} assetClass={active} showTotal />
      </section>

      {sub && sub.labels.length > 1 && (
        <section className="space-y-6">
          <div>
            <h2 className="text-2xl font-light text-ink">How The Holdings Move Together</h2>
            <p className="mt-2 text-sm text-ink-muted">Red = move together, green = offset each other.{active !== "All" && ` Showing ${active} only.`}</p>
          </div>
          <CorrelationHeatmap labels={sub.labels} matrix={sub.matrix} />
        </section>
      )}
    </div>
  );
}

export default HoldingsExplorer;
