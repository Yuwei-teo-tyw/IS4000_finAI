import type { GoalProjection as GP } from "../../../types/arc";
import { at } from "./util";

export function FundingByEvent({ data }: { data: GP }) {
  const evs = [...data.events].sort((a, b) => a.year - b.year).map((e) => {
    const req = at(data.points, e.year, "required");
    const pct = req > 0 ? Math.min(100, Math.round((at(data.points, e.year, "projected") / req) * 100)) : 100;
    return { ...e, pct };
  });
  return (
    <div className="flex flex-col justify-center gap-5">
      {evs.map((e) => (
        <div key={e.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink">{e.label} <span className="text-ink-muted">{e.year}</span></span>
            <span className="text-ink">{e.pct}%</span>
          </div>
          <svg viewBox="0 0 100 4" preserveAspectRatio="none" className="mt-2 h-2 w-full" aria-hidden="true">
            <rect width="100" height="4" className="fill-scale-track" opacity="0.6" />
            <rect width={e.pct} height="4" className="fill-scale-fill" />
          </svg>
        </div>
      ))}
    </div>
  );
}
