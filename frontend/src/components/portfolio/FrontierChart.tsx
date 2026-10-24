import type { PaFrontier, PaPortfolioPoint } from "../../types/portfolio";
import { pct } from "./paFormat";

const W = 520, H = 320, PAD = { l: 52, r: 18, t: 18, b: 44 };

/**
 * Risk (volatility) against expected return. The curve and both points come from the
 * backend's mean-variance model; nothing is drawn when the model has no data.
 */
export function FrontierChart({ frontier, original, adjusted, limitation }: {
  frontier: PaFrontier | null; original: PaPortfolioPoint; adjusted: PaPortfolioPoint; limitation: string | null;
}) {
  const pts = (p: PaPortfolioPoint) =>
    p.model_volatility_pct !== null && p.model_expected_return_pct !== null ? { x: p.model_volatility_pct, y: p.model_expected_return_pct } : null;
  const o = pts(original), a = pts(adjusted);
  if (!frontier || !frontier.points.length) {
    return (
      <div className="rounded-lg border border-dashed border-hairline-strong p-6 text-sm text-ink-700" role="note">
        <p className="font-semibold text-ink">Efficient frontier not available</p>
        <p className="mt-2">{limitation ?? "The backend did not return a frontier."} No curve is drawn rather than an invented one.</p>
      </div>
    );
  }
  const xs = [...frontier.points.map((p) => p.volatility_pct), ...(o ? [o.x] : []), ...(a ? [a.x] : [])];
  const ys = [...frontier.points.map((p) => p.expected_return_pct), ...(o ? [o.y] : []), ...(a ? [a.y] : [])];
  const xMax = Math.max(...xs) * 1.08 || 1, yMin = Math.min(...ys) - 0.3, yMax = Math.max(...ys) + 0.3;
  const sx = (v: number) => PAD.l + (v / xMax) * (W - PAD.l - PAD.r);
  const sy = (v: number) => H - PAD.b - ((v - yMin) / (yMax - yMin)) * (H - PAD.t - PAD.b);
  const path = frontier.points.map((p, i) => `${i ? "L" : "M"}${sx(p.volatility_pct).toFixed(1)} ${sy(p.expected_return_pct).toFixed(1)}`).join(" ");
  const xTicks = Array.from({ length: 5 }, (_, i) => (xMax / 4) * i);
  const yTicks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) / 4) * i);

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label={`Efficient frontier. Proposed portfolio ${o ? `${pct(o.x)} risk, ${pct(o.y, 2)} return` : "not plotted"}; adjusted ${a ? `${pct(a.x)} risk, ${pct(a.y, 2)} return` : "not plotted"}.`}>
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={PAD.t} y2={H - PAD.b} stroke="var(--hairline)" />
            <text x={sx(t)} y={H - PAD.b + 16} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">{t.toFixed(0)}%</text>
          </g>
        ))}
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} stroke="var(--hairline)" />
            <text x={PAD.l - 8} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="var(--ink-muted)">{t.toFixed(1)}%</text>
          </g>
        ))}
        <text x={(W + PAD.l) / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="var(--ink-muted)">Risk: volatility a year</text>
        <text x={14} y={(H - PAD.b) / 2} textAnchor="middle" fontSize="12" fill="var(--ink-muted)" transform={`rotate(-90 14 ${(H - PAD.b) / 2})`}>Expected return a year</text>
        <path d={path} fill="none" stroke="var(--ink)" strokeWidth="2.5" />
        {o && (
          <circle cx={sx(o.x)} cy={sy(o.y)} r="7" fill="var(--surface-100)" stroke="var(--ink)" strokeWidth="2.5">
            <title>{`Proposed: ${pct(o.x)} risk, ${pct(o.y, 2)} return`}</title>
          </circle>
        )}
        {a && (
          <circle cx={sx(a.x)} cy={sy(a.y)} r="6" fill="var(--brand)">
            <title>{`Adjusted: ${pct(a.x)} risk, ${pct(a.y, 2)} return`}</title>
          </circle>
        )}
      </svg>
      <figcaption className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-2"><i className="inline-block h-0.5 w-5 bg-ink" aria-hidden />Efficient frontier</span>
        <span className="inline-flex items-center gap-2"><i className="inline-block h-3 w-3 rounded-full border-2 border-ink" aria-hidden />Proposed portfolio</span>
        <span className="inline-flex items-center gap-2"><i className="inline-block h-3 w-3 rounded-full bg-brand" aria-hidden />Your adjusted weights</span>
      </figcaption>
    </figure>
  );
}
