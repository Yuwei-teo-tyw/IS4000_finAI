import { Table, sgdFull } from "../ui";
import type { AssetClass, Holding } from "../../types/arc";

type H = Holding & { ticker?: string };

export function HoldingsTable({ holdings, assetClass, showTotal = false }: { holdings: Holding[]; assetClass?: AssetClass | "All"; showTotal?: boolean }) {
  const list = (holdings as H[]).filter((h) => !assetClass || assetClass === "All" || h.assetClass === assetClass);
  const sign = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
  const rows = list.map((h) => [
    <div><span className="font-semibold text-ink">{h.name}</span>{h.ticker && <span className="ml-2 text-xs text-ink-muted">{h.ticker}</span>}</div>,
    h.assetClass,
    sgdFull(h.valueSgd),
    <div className="flex items-center gap-3"><div className="h-2 w-24 rounded bg-surface-300"><div className="h-2 rounded bg-surface-inverse" style={{ width: `${Math.min(100, h.weightPct * 4)}%` }} /></div>{h.weightPct}%</div>,
    <span className={h.returnYtdPct >= 0 ? "text-positive" : "text-negative"}>{sign(h.returnYtdPct)}</span>,
  ]);
  if (showTotal && list.length) {
    const value = list.reduce((a, h) => a + h.valueSgd, 0);
    const weight = list.reduce((a, h) => a + h.weightPct, 0);
    const ytd = value ? list.reduce((a, h) => a + h.returnYtdPct * h.valueSgd, 0) / value : 0;
    rows.push([
      <span className="font-semibold text-ink">Total</span>,
      "",
      <span className="font-semibold text-ink">{sgdFull(value)}</span>,
      <span className="font-semibold text-ink">{Math.round(weight * 10) / 10}%</span>,
      <span className={ytd >= 0 ? "font-semibold text-positive" : "font-semibold text-negative"}>{sign(ytd)}</span>,
    ]);
  }
  return <Table head={["Instrument", "Asset class", "Value", "Weight", "YTD"]} rows={rows} />;
}
