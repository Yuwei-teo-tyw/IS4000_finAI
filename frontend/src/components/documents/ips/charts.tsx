import { useState } from "react";
import { NumberInput } from "../../../components/ui/NumberInput";
import { EDIT_BOX } from "./parts";
import type { AllocationRow, Bucket3L } from "../../../types/arc";
import { sgd, SliceTooltip, useSliceTooltip } from "../../ui";

export const BUCKET_BG = { liquidity: "bg-chart-liquidity", longevity: "bg-chart-equities", legacy: "bg-chart-alternatives" } as const;
export const BUCKET_VAR = { liquidity: "var(--chart-liquidity)", longevity: "var(--chart-equities)", legacy: "var(--chart-alternatives)" } as const;
const CLASS_COLOR: Record<string, string> = {
  Cash: "var(--chart-liquidity)", "Fixed income": "var(--chart-bonds)", Equities: "var(--chart-equities)",
};

export function BucketBar({ buckets }: { buckets: Bucket3L[] }) {
  return (
    <div>
      <div className="flex h-6 w-full overflow-hidden border border-hairline" role="img" aria-label="3L bucket allocation">
        {buckets.map((b) => <div key={b.id} className={BUCKET_BG[b.id]} style={{ width: `${b.pct}%` }} />)}
      </div>
      <table className="mt-4 w-full table-fixed border-collapse text-left text-[15px]">
        <thead>
          <tr className="border-b border-hairline text-[12px] leading-4 uppercase tracking-[0.06em] font-normal text-ink-muted">
            <th className="py-2 pr-2 font-light">Bucket</th><th className="py-2 pr-2 font-light">Horizon</th>
            <th className="py-2 pr-2 text-right font-light">Amount (SGD)</th><th className="py-2 text-right font-light">%</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.id} className="avoid-break border-b border-hairline align-top">
              <td className="break-words py-2 pr-2"><i className={`mr-2 inline-block h-3 w-3 ${BUCKET_BG[b.id]}`} />{b.name}</td>
              <td className="break-words py-2 pr-2">{b.horizon}</td>
              <td className="py-2 pr-2 text-right">{sgd(b.amountSgd)}</td>
              <td className="py-2 text-right">{b.pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SaaDonut({ rows }: { rows: AllocationRow[] }) {
  const r = 70, c = 2 * Math.PI * r;
  const total = rows.reduce((s, x) => s + x.saa, 0) || 1;
  const groups = [
    { label: "Cash", v: 0, col: CLASS_COLOR.Cash }, { label: "Fixed income", v: 0, col: CLASS_COLOR["Fixed income"] },
    { label: "Equities", v: 0, col: CLASS_COLOR.Equities }, { label: "Alternatives", v: 0, col: "var(--chart-alternatives)" },
  ];
  rows.forEach((x) => { (groups.find((g) => g.label === x.assetClass) ?? groups[3]).v += x.saa; });
  let offset = 0;
  const tt = useSliceTooltip();
  return (
    <div className="grid grid-cols-1 gap-8 sm:grid-cols-[200px_1fr]">
      <div className="space-y-4">
        <div ref={tt.containerRef} className="relative h-[200px] w-[200px]">
        <svg viewBox="0 0 200 200" className="h-[200px] w-[200px]" role="img" aria-label="Strategic asset allocation">
          <g transform="rotate(-90 100 100)">
            <circle cx="100" cy="100" r={r} fill="none" stroke="var(--scale-track)" strokeWidth="28" />
            {groups.filter((g) => g.v > 0).map((g) => {
              const len = (g.v / total) * c;
              const el = <circle key={g.label} cx="100" cy="100" r={r} fill="none" stroke={g.col} strokeWidth="28" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} {...tt.bind(g.label, (g.v / total) * 100)} style={tt.sliceStyle(g.label)} />;
              offset += len;
              return el;
            })}
          </g>
          <text x="100" y="105" textAnchor="middle" fontSize="14" fill="var(--ink)">SAA</text>
        </svg>
        <SliceTooltip tip={tt.tip} />
        </div>
        <ul className="space-y-1 text-[13px]">
          {groups.filter((g) => g.v > 0).map((g) => (
            <li key={g.label} className="flex items-center gap-2"><i className="inline-block h-3 w-3" style={{ background: g.col }} />{g.label}<span className="ml-auto">{g.v}%</span></li>
          ))}
        </ul>
      </div>
      <SaaRows rows={rows} />
    </div>
  );
}

export function SaaRows({ rows }: { rows: AllocationRow[] }) {
  return (
    <ul className="min-w-0 space-y-2">
      {rows.map((a) => (
        <li key={a.assetClass} className="avoid-break break-words border-b border-hairline pb-2">
          {a.assetClass} {a.saa}% <span className="text-ink-muted">(min {Math.max(0, a.saa - a.band)}% – max {a.saa + a.band}%)</span>
        </li>
      ))}
    </ul>
  );
}

/* ---------- Strategy donut: one strategy's strategic asset allocation with % legend ---------- */

export const STRAT_COLOR: Record<string, string> = {
  Bonds: "var(--chart-bonds)", Liquidity: "var(--chart-liquidity)", Equities: "var(--chart-equities)",
  "Alternative Investments": "var(--chart-alternatives)", Other: "var(--ink-muted)",
};

/** `editable`: the legend percentages become number inputs (one per asset class in `keys`); the value is clamped by `onCommit` on blur. */
export function StrategyDonut({ allocation, label, hideLegend = false, editable }: { allocation?: Record<string, number>; label: string; hideLegend?: boolean; editable?: { keys: string[]; onCommit: (k: string, raw: string) => void } }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const r = 60, c = 2 * Math.PI * r;
  const rows = Object.entries(allocation ?? {}).filter(([, v]) => v > 0);
  const total = rows.reduce((s, [, v]) => s + v, 0) || 1;
  let offset = 0;
  return (
    <div className="flex min-w-0 flex-col items-center gap-4 sm:flex-row" data-testid="strategy-donut">
      <svg viewBox="0 0 160 160" className="h-[160px] w-[160px] shrink-0" role="img" aria-label={label}>
        <g transform="rotate(-90 80 80)">
          <circle cx="80" cy="80" r={r} fill="none" stroke="var(--scale-track)" strokeWidth="26" />
          {rows.map(([k, v]) => {
            const len = (v / total) * c;
            const el = <circle key={k} data-slice={k} cx="80" cy="80" r={r} fill="none" stroke={STRAT_COLOR[k] ?? "var(--ink-muted)"} strokeWidth="26" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}><title>{`${k} ${v}%`}</title></circle>;
            offset += len;
            return el;
          })}
        </g>
        {!rows.length && <text x="80" y="84" textAnchor="middle" fontSize="12" fill="var(--ink-muted)">No strategy</text>}
      </svg>
      {!hideLegend && editable && <ul className="min-w-0 flex-1 space-y-1 self-stretch text-[13px]">
        {editable.keys.map((k) => (
          <li key={k} className="flex items-center gap-2"><i className="inline-block h-3 w-3 shrink-0" style={{ background: STRAT_COLOR[k] ?? "var(--ink-muted)" }} />{k}
            <span className="ml-auto flex items-center gap-1">
              <NumberInput step="0.1" value={draft[k] ?? String(allocation?.[k] ?? 0)} aria-label={`${k} percent`}
                onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
                onBlur={(e) => { editable.onCommit(k, e.target.value); setDraft((d) => { const { [k]: _x, ...r } = d; return r; }); }}
                className={`w-16 px-1 py-0.5 text-right text-[13px] ${EDIT_BOX}`} />%
            </span>
          </li>
        ))}
      </ul>}
      {!hideLegend && !editable && <ul className="min-w-0 flex-1 space-y-1 self-stretch text-[13px]">
        {rows.map(([k, v]) => (
          <li key={k} className="flex items-center gap-2"><i className="inline-block h-3 w-3 shrink-0" style={{ background: STRAT_COLOR[k] ?? "var(--ink-muted)" }} />{k}<span className="ml-auto">{v}%</span></li>
        ))}
      </ul>}
    </div>
  );
}
