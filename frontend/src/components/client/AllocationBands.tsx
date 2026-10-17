import type { AllocationRow } from "../../types/arc";

export type AllocMode = "saa" | "taa";

/** One row per asset class: target marker with ±band shaded zone, current bar, and target bar. */
export function AllocationBands({ rows, mode }: { rows: AllocationRow[]; mode: AllocMode }) {
  const max = 50;
  const pos = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  return (
    <div className="flex flex-col gap-8">
      {rows.map((r) => {
        const target = mode === "saa" ? r.saa : r.newTaa;
        const lo = Math.max(0, target - r.band), hi = target + r.band;
        const out = r.current < lo || r.current > hi;
        return (
          <div key={r.assetClass}>
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm font-semibold text-ink">{r.assetClass}</span>
              <span className={`text-sm ${out ? "font-semibold text-negative" : "text-ink-500"}`}>
                current {r.current}% · {mode.toUpperCase()} {target}% · band {lo}–{hi}%{out ? " · outside band" : ""}
              </span>
            </div>
            <div className="relative h-8 rounded bg-surface-300">
              <div className="absolute inset-y-0 rounded bg-surface-300" style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }} />
              <div className="absolute left-0 top-1 h-3 rounded-r bg-surface-inverse" style={{ width: pos(r.current) }} />
              <div className="absolute bottom-1 left-0 h-3 rounded-r bg-brand text-on-brand" style={{ width: pos(target) }} />
              <div className="absolute inset-y-0 w-0.5 bg-surface-inverse" style={{ left: pos(target) }} />
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap gap-6 text-xs text-ink-500">
        <span><i className="mr-2 inline-block h-2 w-5 rounded bg-surface-inverse" />Current</span>
        <span><i className="mr-2 inline-block h-2 w-5 rounded bg-brand text-on-brand" />{mode.toUpperCase()} target</span>
        <span><i className="mr-2 inline-block h-2 w-5 rounded bg-surface-300" />±5 point band</span>
      </div>
    </div>
  );
}
