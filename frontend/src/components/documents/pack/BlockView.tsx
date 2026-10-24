import { AllocationDonut } from "../../client/AllocationDonut";
import { HoldingsTable } from "../../client/HoldingsTable";
import { TaaPie } from "../../pm/TaaPie";
import { usePmProgress } from "../../../services/workflowStore";
import { BulletList, Loading, Table } from "../../ui";
import type { PackBlock } from "../../../types/arc";
import { CHART_LABEL, liveSlices, TABLE_LABEL, useBlockData, type ChartBlock } from "./useBlockData";

const COLORS = ["chart-liquidity", "chart-bonds", "chart-equities", "chart-alternatives", "ink-muted", "hairline"];
const TITLES: Record<ChartBlock["chart"], [string, string]> = { saa: ["Strategic", "allocation"], taa: ["New", "TAA"], holdings: ["Holdings", "weights"], allocation: ["Current", "allocation"] };

function Caption({ text }: { text?: string }) {
  return text ? <p className="mt-3 text-[13px] font-light text-ink-muted">{text}</p> : null;
}

/** Chart block: LIVE from current data unless a frozen snapshot is set. */
export function ChartBlockView({ block, clientId }: { block: ChartBlock; clientId: string }) {
  const d = useBlockData(block.clientId ?? clientId);
  const slices = block.snapshot ?? liveSlices(block.chart, d);
  if (!block.snapshot && !d.ready) return <Loading />;
  return (
    <figure className="avoid-break">
      {block.chart === "taa"
        ? <TaaPie labels={slices.map((s) => s.label)} values={slices.map((s) => s.value)} />
        : <AllocationDonut title={TITLES[block.chart]} slices={slices.map((s, i) => ({ label: s.label, value: s.value, color: COLORS[i % COLORS.length] }))} />}
      <Caption text={block.caption} />
    </figure>
  );
}

export function TableBlockView({ block, clientId }: { block: Extract<PackBlock, { type: "table" }>; clientId: string }) {
  const d = useBlockData(clientId);
  const prog = usePmProgress(clientId);
  if (!d.ready) return <Loading />;
  const reasonOf = (cls: string, fallback: string) => (prog.taaReasons?.[cls] ?? fallback).split(/\r?\n/).map((l) => l.replace(/^\s*[•\-*]\s*/, "").trim()).filter(Boolean);
  const sign = (n: number) => `${n > 0 ? "+" : ""}${Math.round(n * 10) / 10}`;
  return (
    <figure className="avoid-break">
      {block.table === "taa"
        ? <Table head={["Asset class", "Previous TAA", "New TAA", "Change (pts)", "Reason"]} rows={d.alloc!.map((r, i) => [r.assetClass, `${r.oldTaa}%`, `${d.newTaa[i] ?? r.newTaa}%`, sign((d.newTaa[i] ?? r.newTaa) - r.oldTaa),
          <div className="min-w-[10rem] space-y-1 whitespace-normal break-words text-[13px] font-light leading-6 text-ink [overflow-wrap:anywhere]">{reasonOf(r.assetClass, r.reason).map((l, k) => <p key={k}>{l}</p>)}</div>])} />
        : <HoldingsTable holdings={d.holdings!} showTotal />}
      <Caption text={block.caption ?? undefined} />
    </figure>
  );
}

export function BlockItem({ block, clientId }: { block: PackBlock; clientId: string }) {
  switch (block.type) {
    case "text": return block.text.trim() ? <BulletList text={block.text} /> : null;
    case "image": return (
      <figure className="avoid-break"><img src={block.src} alt={block.alt} className="max-h-[480px] max-w-full border border-hairline" /><Caption text={block.caption} /></figure>
    );
    case "chart": return <ChartBlockView block={block} clientId={clientId} />;
    case "table": return <TableBlockView block={block} clientId={clientId} />;
  }
}

/** Read-only render of a block list. */
export function BlockView({ blocks, clientId }: { blocks: PackBlock[]; clientId: string }) {
  return <div className="space-y-8">{blocks.map((b) => <BlockItem key={b.id} block={b} clientId={clientId} />)}</div>;
}

export { CHART_LABEL, TABLE_LABEL };
