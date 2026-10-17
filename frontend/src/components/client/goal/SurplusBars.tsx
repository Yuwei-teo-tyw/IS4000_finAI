import type { GoalProjection as GP } from "../../../types/arc";
import { at } from "./util";

const W = 480, H = 280, L = 44, R = 12, T = 16, B = 36;

export function SurplusBars({ data }: { data: GP }) {
  const { points } = data;
  const x0 = points[0].year, x1 = points[points.length - 1].year;
  const years: number[] = [];
  for (let y = x0; y <= x1; y += 5) years.push(y);
  if (years[years.length - 1] !== x1) years.push(x1);
  const vals = years.map((y) => ({ y, v: at(points, y, "projected") - at(points, y, "required") }));
  const m = Math.max(1, ...vals.map((d) => Math.abs(d.v)));
  const half = (H - T - B) / 2, zero = T + half, bw = ((W - L - R) / vals.length) * 0.6;
  const cx = (i: number) => L + ((i + 0.5) * (W - L - R)) / vals.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Projected minus required wealth every five years, S$ millions">
      {vals.map((d, i) => {
        const h = (Math.abs(d.v) / m) * half;
        return (
          <g key={d.y}>
            <rect x={cx(i) - bw / 2} y={d.v >= 0 ? zero - h : zero} width={bw} height={Math.max(h, 1)} className={d.v >= 0 ? "fill-positive" : "fill-negative"} />
            <text x={cx(i)} y={H - 12} textAnchor="middle" className="fill-ink-muted" fontSize="13">{d.y}</text>
          </g>
        );
      })}
      <line x1={L} x2={W - R} y1={zero} y2={zero} className="stroke-ink" strokeWidth="1" />
      <text x={L - 6} y={zero + 4} textAnchor="end" className="fill-ink-muted" fontSize="13">0</text>
      <text x={L - 6} y={T + 8} textAnchor="end" className="fill-ink-muted" fontSize="13">+{Math.round(m)}</text>
      <text x={L - 6} y={H - B} textAnchor="end" className="fill-ink-muted" fontSize="13">-{Math.round(m)}</text>
    </svg>
  );
}
