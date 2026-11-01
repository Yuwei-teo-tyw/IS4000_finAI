import { SliceTooltip, useSliceTooltip } from "../ui";
import { ringPath } from "../../utils/ringPath";
const PALETTE = ["var(--chart-liquidity)", "var(--chart-bonds)", "var(--chart-equities)", "var(--chart-alternatives)", "var(--ink-muted)", "var(--hairline)"];

/** Live donut of the TAA values being edited. Slices are normalised to the entered total; a note flags total != 100. */
export function TaaPie({ labels, values, title = "New TAA" }: { labels: string[]; values: number[]; title?: string }) {
  const r = 70, c = 2 * Math.PI * r;
  const vals = labels.map((_, i) => Math.max(0, values[i] || 0));
  const total = vals.reduce((s, v) => s + v, 0);
  let offset = 0;
  const tt = useSliceTooltip();
  return (
    <div className="relative space-y-6" ref={tt.containerRef}>
      <svg viewBox="0 0 200 200" className="mx-auto h-[220px] w-[220px] max-w-full" role="img" aria-label={title}>
        <g>
          <path d={ringPath(100, 100, r + 14, r - 14, 0, 1)} fill="var(--scale-track)" fillRule="evenodd" />
          {total > 0 && vals.map((v, i) => {
            if (v <= 0) return null;
            const len = (v / total) * c;
            const el = <path key={labels[i]} d={ringPath(100, 100, r + 14, r - 14, offset / c, (offset + len) / c)} fill={PALETTE[i % PALETTE.length]} fillRule="evenodd" {...tt.bind(labels[i], total ? Math.round((v / total) * 1000) / 10 : 0)} style={tt.sliceStyle(labels[i])} />;
            offset += len;
            return el;
          })}
        </g>
        <text x="100" y="105" textAnchor="middle" fontSize="14" fill="var(--ink)">{title}</text>
      </svg>
      <ul className="space-y-2 text-[13px]">
        {labels.map((l, i) => (
          <li key={l} className="flex items-center gap-2"><i className="inline-block h-3 w-3" style={{ background: PALETTE[i % PALETTE.length] }} />{l}<span className="ml-auto">{vals[i]}%</span></li>
        ))}
      </ul>
      <SliceTooltip tip={tt.tip} />
      {total !== 100 && <p className="text-[13px] text-ink-muted" role="status">Total is {total}%, not 100%.</p>}
    </div>
  );
}
