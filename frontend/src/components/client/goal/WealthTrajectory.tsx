import type { GoalProjection as GP } from "../../../types/arc";
import { at } from "./util";

const W = 480, H = 300, L = 40, R = 16, T = 16, B = 64;

export function WealthTrajectory({ data }: { data: GP }) {
  const { points, events } = data;
  const x0 = points[0].year, x1 = points[points.length - 1].year;
  const max = Math.max(...points.flatMap((p) => [p.projected, p.required]));
  const step = max > 40 ? 10 : max > 20 ? 5 : 2;
  const yMax = Math.ceil(max / step) * step;
  const X = (y: number) => L + ((y - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v: number) => T + (1 - v / yMax) * (H - T - B);
  const line = (k: "projected" | "required") => points.map((p, i) => `${i ? "L" : "M"}${X(p.year).toFixed(1)},${Y(p[k]).toFixed(1)}`).join(" ");
  const area = `${line("projected")} L${X(x1)},${Y(0)} L${X(x0)},${Y(0)} Z`;
  const ticks = Array.from({ length: yMax / step + 1 }, (_, i) => i * step);
  const evs = [...events].sort((a, b) => a.year - b.year);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Projected against required wealth, S$ millions">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} className="stroke-hairline-strong" strokeWidth="1" opacity="0.5" />
            <text x={L - 6} y={Y(t) + 4} textAnchor="end" className="fill-ink-muted" fontSize="13">{t}</text>
          </g>
        ))}
        <path d={area} className="fill-scale-track" opacity="0.5" />
        <path d={line("required")} fill="none" className="stroke-scale-fill" strokeWidth="2" strokeDasharray="6 4" />
        <path d={line("projected")} fill="none" className="stroke-ink" strokeWidth="2.5" />
        {evs.map((e, i) => (
          <g key={e.label}>
            <circle cx={X(e.year)} cy={Y(at(points, e.year, "projected"))} r="5" className="fill-ink" />
            <text x={X(e.year)} y={H - B + 20 + (i % 2) * 18} textAnchor="middle" className="fill-ink" fontSize="13">{e.year}</text>
          </g>
        ))}
        <text x={L} y={H - 6} className="fill-ink-muted" fontSize="13">S$m · solid projected, dashed required</text>
      </svg>
    </div>
  );
}
