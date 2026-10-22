import { arcApi } from "../../../services/arcApi";
import { usePmProgress } from "../../../services/workflowStore";
import { useAsync } from "../../ui";
import type { PackBlock } from "../../../types/arc";

export type ChartBlock = Extract<PackBlock, { type: "chart" }>;
export type Slice = { label: string; value: number };
const r1 = (n: number) => Math.round(n * 10) / 10;

/** Live data for chart/table blocks: current allocation + holdings, with the PM's saved TAA and holding edits applied. */
export function useBlockData(clientId: string) {
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const holdings = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const p = usePmProgress(clientId);
  const newTaa = alloc ? (p.taa && p.taa.length === alloc.length ? p.taa : alloc.map((r) => r.newTaa)) : [];
  const liveHoldings = holdings?.map((h) => ({ ...h, weightPct: r1(p.holdings?.[h.id] ?? h.weightPct) }));
  return { alloc, holdings: liveHoldings, newTaa, ready: !!alloc && !!holdings };
}

export function liveSlices(chart: ChartBlock["chart"], d: ReturnType<typeof useBlockData>): Slice[] {
  if (!d.alloc || !d.holdings) return [];
  if (chart === "saa") return d.alloc.map((r) => ({ label: r.assetClass, value: r.saa }));
  if (chart === "allocation") return d.alloc.map((r) => ({ label: r.assetClass, value: r.current }));
  if (chart === "taa") return d.alloc.map((r, i) => ({ label: r.assetClass, value: d.newTaa[i] ?? r.newTaa }));
  return d.holdings.map((h) => ({ label: h.name, value: h.weightPct }));
}

export const CHART_LABEL: Record<ChartBlock["chart"], string> = { saa: "Strategic asset allocation (SAA)", taa: "Tactical asset allocation (new TAA)", holdings: "Holdings weights", allocation: "Current allocation" };
export const TABLE_LABEL = { taa: "TAA: previous versus new", holdings: "Holdings" } as const;
