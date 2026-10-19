import type { ReactNode } from "react";
import type { PmOption, PmResponse } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Card, Table } from "../ui";
import { DASH, pct, sgdAmt } from "./pmFormat";

function Bar({ value, max, tone }: { value: number | null; max: number; tone: "ink" | "brand" }) {
  if (value === null) return <span className="text-xs text-ink-muted">Not calculable</span>;
  const w = max > 0 ? Math.max(2, Math.min(100, (Math.abs(value) / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="h-2.5 flex-1 rounded-sm bg-scale-track">
        <div className={`h-full rounded-sm ${tone === "brand" ? "bg-negative" : "bg-scale-fill"}`} style={{ width: `${w}%` }} />
      </div>
      <span className="w-14 text-right text-sm text-ink">{pct(value)}</span>
    </div>
  );
}

const top = (rec: Record<string, number> | null | undefined, n = 3) =>
  rec ? Object.entries(rec).slice(0, n).map(([k, v]) => `${k} ${v.toFixed(0)}%`).join(", ") : "not available";

const lines = (items: string[]) => (
  <ul className="list-disc space-y-1 pl-4">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
);

/** Offered options side by side. Same scale for return and downside; no "best" marker beyond the agent's labelled preference. */
export function PortfolioCompare({ response }: { response: PmResponse }) {
  const offered = response.portfolio_options.filter(isOffered);
  const withdrawn = response.portfolio_options.filter((o) => !isOffered(o));
  const fit = (criterion: string) => (o: PmOption) => response.comparison_matrix.find((r) => r.criterion === criterion)?.values[o.option_id] ?? DASH;
  const max = Math.max(1, ...offered.flatMap((o) => [o.expected_portfolio_return ?? 0, o.metrics?.estimated_stress_drawdown_pct ?? 0]));

  const rows: [string, (o: PmOption) => ReactNode][] = [
    ["Objective", (o) => o.objective],
    ["Asset allocation", (o) => lines(o.asset_allocation.map((a) => `${a.asset_class} ${pct(a.allocation_percentage)}`))],
    ["Expected return (assumption)", (o) => <><p className="text-ink">{pct(o.expected_portfolio_return, 2)} p.a.</p><p className="text-xs text-ink-muted">Product yields for cash and bonds; house assumptions for other assets; after fees.</p></>],
    ["Expansion / slowdown / recession", (o) => lines(o.scenario_analysis.map((s) => `${s.scenario}: ${pct(s.portfolio_return_pct, 1, true)}`))],
    ["Risk and downside", (o) => <><p className="text-ink">{o.estimated_risk_level ?? DASH}</p><p>Stress drawdown {pct(o.metrics?.estimated_stress_drawdown_pct)} ({sgdAmt(o.eligible_portfolio_value && o.metrics?.estimated_stress_drawdown_pct != null ? (o.eligible_portfolio_value * o.metrics.estimated_stress_drawdown_pct) / 100 : null)})</p></>],
    ["Liquidity", (o) => <><p className="text-ink">{pct(o.metrics?.high_liquidity_share_pct, 0)} daily dealing</p><p className="text-xs text-ink-muted">{o.liquidity_assessment}</p></>],
    ["Fees and costs", (o) => <><p className="text-ink">{pct(o.metrics?.estimated_annual_fee_pct, 2)} p.a. ({sgdAmt(o.metrics?.estimated_annual_fee_amount)} a year)</p><p className="text-xs text-ink-muted">One-off dealing {sgdAmt(o.metrics?.estimated_one_off_transaction_cost)}</p></>],
    ["Diversification", (o) => <><p>{o.metrics?.number_of_products} products, {o.metrics?.number_of_asset_classes} asset classes</p><p className="text-xs text-ink-muted">Regions: {top(o.metrics?.geographic_exposure_pct)}</p><p className="text-xs text-ink-muted">Sectors: {top(o.metrics?.sector_exposure_pct)}</p></>],
    ["Currency exposure", (o) => `${pct(o.metrics?.foreign_currency_exposure_pct)} unhedged foreign currency`],
    ["Risk appetite fit", fit("Alignment with risk appetite")],
    ["Risk capacity fit", fit("Alignment with risk capacity")],
    ["Goal alignment", (o) => o.goal_alignment.length ? lines(o.goal_alignment.map((g) => `${g.goal}: ${g.status.replace("_", " ").toLowerCase()}`)) : DASH],
    ["Advantages", (o) => lines(o.advantages)],
    ["Disadvantages", (o) => lines(o.disadvantages)],
  ];

  return (
    <div className="flex flex-col gap-10">
      <Card>
        <p className="text-lg">Return assumption against estimated downside</p>
        <p className="mt-1 text-sm text-ink-muted">Same scale for both. Higher expected return comes with a larger potential loss.</p>
        <div className="mt-8 flex flex-col gap-6">
          {offered.map((o) => (
            <div key={o.option_id} className="grid items-center gap-4 md:grid-cols-[200px_1fr_1fr]">
              <p className="text-sm text-ink">{o.option_id} · {o.option_name}{response.preferred_option === o.option_id ? " (agent's preference)" : ""}</p>
              <div><p className="mb-1 text-xs text-ink-muted">Expected return a year</p><Bar value={o.expected_portfolio_return} max={max} tone="ink" /></div>
              <div><p className="mb-1 text-xs text-ink-muted">Stress drawdown</p><Bar value={o.metrics?.estimated_stress_drawdown_pct ?? null} max={max} tone="brand" /></div>
            </div>
          ))}
        </div>
        {withdrawn.length > 0 && (
          <div className="mt-8 border-t border-hairline pt-5 text-sm text-ink-muted">
            <p className="text-xs font-semibold uppercase tracking-[0.12em]">Not offered</p>
            <ul className="mt-2 space-y-1">{withdrawn.map((o) => <li key={o.option_id}><span className="text-ink">{o.option_id} · {o.option_name}:</span> {o.suitability_explanation}</li>)}</ul>
          </div>
        )}
      </Card>
      <Table
        head={["Criterion", ...offered.map((o) => `${o.option_id} · ${o.option_name}`)]}
        rows={rows.map(([label, render]) => [<span key="l" className="font-semibold text-ink">{label}</span>, ...offered.map((o) => <div key={o.option_id} className="min-w-[180px] text-sm text-ink-700">{render(o)}</div>)])}
      />
    </div>
  );
}
