import { SliceTooltip, useSliceTooltip } from "../ui";

export interface DonutSlice { label: string; value: number; color: string }
const toVar = (c: string) => (c.startsWith("var(") ? c : `var(--${c.replace(/^--/, "")})`);

/** Inline-SVG donut with a legend (name left, % right). Every slice is labelled in text. */
export function AllocationDonut({ slices, title }: { slices: DonutSlice[]; title?: [string, string] }) {
  const r = 70, c = 2 * Math.PI * r;
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  let offset = 0;
  const tt = useSliceTooltip();
  return (
    <div className="flex flex-wrap items-center gap-10">
      <div ref={tt.containerRef} className="relative shrink-0">
      <svg viewBox="0 0 200 200" className="h-[200px] w-[200px] shrink-0" role="img" aria-label={title ? `${title[0]} ${title[1]}` : "Current allocation"}>
        <g transform="rotate(-90 100 100)">
          <circle cx="100" cy="100" r={r} fill="none" stroke="var(--scale-track)" strokeWidth="28" />
          {slices.map((s) => {
            const len = (s.value / total) * c;
            const el = (
              <circle key={s.label} cx="100" cy="100" r={r} fill="none" stroke={toVar(s.color)} strokeWidth="28"
                strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}
                {...tt.bind(s.label, (s.value / total) * 100)} style={tt.sliceStyle(s.label)} />
            );
            offset += len;
            return el;
          })}
        </g>
        <text x="100" y="96" textAnchor="middle" fontSize="12" fill="var(--ink-muted)">{title?.[0] ?? "Current"}</text>
        <text x="100" y="116" textAnchor="middle" fontSize="16" fill="var(--ink)">{title?.[1] ?? "allocation"}</text>
      </svg>
      <SliceTooltip tip={tt.tip} />
      </div>
      <ul className="min-w-[200px] flex-1 space-y-4 text-sm">
        {slices.map((s) => (
          <li key={s.label} className="flex items-center gap-3 border-b border-hairline pb-3">
            <i className="inline-block h-3 w-3 shrink-0" style={{ background: toVar(s.color) }} />
            <span className="text-ink">{s.label}</span>
            <span className="ml-auto text-ink">{s.value}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
