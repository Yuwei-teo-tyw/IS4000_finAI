import type { PmOption } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Badge, Card, Table } from "../ui";
import { currentYield, DASH, fx, historical, LIQUIDITY, pct, sgdAmt, STATUS_LABEL } from "./pmFormat";

const ASSETS = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"];
const CHECK_TONE = { PASS: "green", FAIL: "red", UNVERIFIED: "amber", NOT_APPLICABLE: "grey" } as const;

/** One option in full: the agent's mix against the template, its products, and its checks. */
export function OptionDetail({ option, templateSplit, liquiditySgd }: { option: PmOption | undefined; templateSplit: number[]; liquiditySgd: number | null }) {
  if (!option) return <Card><p className="text-ink-muted">Pick a template to see the agent's version of it.</p></Card>;
  if (!isOffered(option)) {
    return (
      <Card>
        <h3 className="text-xl">{option.option_id} · {option.option_name}</h3>
        <div className="mt-4"><Badge tone="grey">{STATUS_LABEL[option.suitability_status]}</Badge></div>
        <p className="mt-4 max-w-3xl text-ink-700">{option.suitability_explanation}</p>
      </Card>
    );
  }
  const agent = Object.fromEntries(option.asset_allocation.map((a) => [a.asset_class, a]));
  return (
    <div className="flex flex-col gap-10">
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h3 className="text-xl">{option.option_id} · {option.option_name}: agent's allocation</h3>
          <Badge tone="green">{STATUS_LABEL[option.suitability_status]}</Badge>
        </div>
        <p className="mt-2 text-sm text-ink-muted">
          Invests {sgdAmt(option.eligible_portfolio_value)}. The Liquidity bucket ({sgdAmt(liquiditySgd)}) is held separately in cash and is not part of these figures.
        </p>
        <div className="mt-8 flex flex-col gap-5">
          {ASSETS.map((a, i) => {
            const share = agent[a]?.allocation_percentage ?? 0;
            const tpl = templateSplit[i] ?? 0;
            if (!share && !tpl) return null;
            return (
              <div key={a}>
                <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="text-ink">{a}</span>
                  <span className="text-ink-muted">template {tpl}% · agent {pct(share, 2)} · {sgdAmt(agent[a]?.investment_amount ?? 0)}</span>
                </div>
                <div className="relative h-3 rounded-sm bg-scale-track">
                  <div className="absolute inset-y-0 left-0 rounded-sm bg-scale-fill" style={{ width: `${Math.min(100, share * 1.5)}%` }} />
                  <div className="absolute inset-y-[-3px] w-0.5 bg-ink" style={{ left: `${Math.min(100, tpl * 1.5)}%` }} title={`Template ${tpl}%`} />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-4 text-xs text-ink-muted">Bar = agent's allocation. Black line = template weight.</p>
        {option.suitability_status === "SUITABLE_WITH_MODIFICATIONS" && (
          <p className="mt-6 text-sm text-ink-700"><span className="font-semibold">Why it differs from the template: </span>{option.suitability_explanation.replace(/^Template adapted to the client's circumstances: /, "")}</p>
        )}
      </Card>

      <div>
        <h3 className="mb-2 text-xl">Products</h3>
        <p className="mb-5 text-sm text-ink-muted">Past returns, current yield and return assumption measure different things and are shown separately. All products are illustrative mock data.</p>
        <Table
          head={["Product", "Amount", "Past returns · historical", "Current yield", "Return assumption · forecast", "Fee p.a.", "Dealing", "Currency"]}
          rows={option.product_selections.map((p) => [
            <div key="n" className="min-w-[220px]"><p className="text-ink">{p.product_name}</p><p className="text-xs text-ink-muted">{p.product_id} · {p.details.sub_asset_class ?? p.asset_class}</p></div>,
            <div key="a"><p className="text-ink">{sgdAmt(p.investment_amount)}</p><p className="text-xs text-ink-muted">{pct(p.allocation_percentage, 2)}</p></div>,
            historical(p.details),
            currentYield(p.details),
            p.expected_return_assumption !== null ? pct(p.expected_return_assumption, 2) : DASH,
            pct(p.management_fee, 2),
            <span key="l">{p.liquidity ? LIQUIDITY[p.liquidity] ?? p.liquidity : DASH}{p.details.lock_in_period && p.details.lock_in_period !== "none" ? `, lock-in ${p.details.lock_in_period}` : ""}</span>,
            fx(p.currency, p.currency_hedged),
          ])}
        />
      </div>

      <Card>
        <h3 className="text-xl">Constraint checks</h3>
        <ul className="mt-5 flex flex-col gap-4">
          {option.constraint_checks.map((c) => (
            <li key={c.constraint} className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline pb-3 text-sm">
              <span className="text-ink">{c.constraint}</span>
              <span className="flex items-center gap-3 text-ink-muted">
                {c.actual !== null && <span>actual {c.actual.toFixed(1)}%{c.limit !== null ? ` · limit ${c.limit}%` : ""}</span>}
                <Badge tone={CHECK_TONE[c.status]}>{c.status.replace("_", " ").toLowerCase()}</Badge>
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
