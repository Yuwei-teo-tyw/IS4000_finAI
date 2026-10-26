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
      <table className="mt-4 w-full table-fixed border-collapse text-left text-[14px]">
        <thead>
          <tr className="border-b border-hairline text-[12px] uppercase tracking-[0.06em] text-ink-muted">
            <th className="py-2 pr-2 font-normal">Bucket</th><th className="py-2 pr-2 font-normal">Horizon</th>
            <th className="py-2 pr-2 text-right font-normal">Amount (SGD)</th><th className="py-2 text-right font-normal">%</th>
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
