import type { ClassAlloc } from "./allocation";
import { classColor } from "./allocation";
import { pct, sgdAmt } from "./pmFormat";

/** Stacked bar of the whole portfolio, labelled with every asset class. */
export function AllocationBar({ rows, height = "h-3" }: { rows: ClassAlloc[]; height?: string }) {
  return (
    <div className={`flex w-full overflow-hidden rounded-sm bg-scale-track ${height}`} role="img"
      aria-label={rows.map((r) => `${r.assetClass} ${pct(r.pct)}`).join(", ")}>
      {rows.filter((r) => r.pct > 0).map((r) => (
        <div key={r.assetClass} style={{ width: `${r.pct}%`, background: classColor(r.assetClass) }} title={`${r.assetClass} ${pct(r.pct, 2)}`} />
      ))}
    </div>
  );
}

/** Every asset class in the portfolio with its weight, amount and (optionally) sub-classes. */
export function AllocationView({ rows, showSubs = true, showAmounts = true }: { rows: ClassAlloc[]; showSubs?: boolean; showAmounts?: boolean }) {
  return (
    <div>
      <AllocationBar rows={rows} />
      <ul className="mt-4 flex flex-col gap-2 text-sm">
        {rows.map((r) => (
          <li key={r.assetClass}>
            <div className="flex items-center gap-3">
              <i className="inline-block h-2.5 w-2.5 shrink-0" style={{ background: classColor(r.assetClass) }} aria-hidden />
              <span className="text-ink">{r.assetClass}</span>
              <span className="ml-auto text-ink">{pct(r.pct)}</span>
              {showAmounts && <span className="w-28 text-right text-ink-muted">{sgdAmt(r.amount)}</span>}
            </div>
            {showSubs && r.subs.length > 1 && (
              <ul className="mt-1 flex flex-col gap-0.5 pl-6 text-xs text-ink-muted">
                {r.subs.map((s) => (
                  <li key={s.name} className="flex gap-3">
                    <span>{s.name}</span>
                    <span className="ml-auto">{pct(s.pct)}</span>
                    {showAmounts && <span className="w-28 text-right">{sgdAmt(s.amount)}</span>}
                  </li>
                ))}
              </ul>
            )}
            {showSubs && r.subs.length === 1 && r.subs[0].name !== r.assetClass && (
              <p className="pl-6 text-xs text-ink-muted">{r.subs[0].name}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
