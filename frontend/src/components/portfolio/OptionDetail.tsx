import type { PmOption } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Badge, Card, Table } from "../ui";
import { allocationOf } from "./allocation";
import { AllocationView } from "./AllocationView";
import { currentYield, DASH, fx, historical, LIQUIDITY, pct, sgdAmt, STATUS_LABEL } from "./pmFormat";

const CHECK_TONE = { PASS: "green", FAIL: "red", UNVERIFIED: "amber", NOT_APPLICABLE: "grey" } as const;

/** One proposed portfolio in full: every asset class and sub-class, its products, and its checks. */
export function OptionDetail({ option, liquiditySgd }: { option: PmOption | undefined; liquiditySgd: number | null }) {
  if (!option) return <Card><p className="text-ink-muted">Select a portfolio to see it in detail.</p></Card>;
  if (!isOffered(option)) {
    return (
      <Card>
        <h3 className="text-xl">{option.option_id} · {option.option_name}</h3>
        <div className="mt-4"><Badge tone="grey">{STATUS_LABEL[option.suitability_status]}</Badge></div>
        <p className="mt-4 max-w-3xl text-ink-700">{option.suitability_explanation}</p>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-10">
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h3 className="text-xl">{option.option_id} · {option.option_name}: asset allocation</h3>
          <Badge tone="green">{STATUS_LABEL[option.suitability_status]}</Badge>
        </div>
        <p className="mt-2 text-sm text-ink-muted">
          Invests {sgdAmt(option.eligible_portfolio_value)}. The Liquidity bucket ({sgdAmt(liquiditySgd)}) is held separately in cash and is not part of these figures.
        </p>
        <div className="mt-8 max-w-2xl"><AllocationView rows={allocationOf(option)} /></div>
        {option.suitability_status === "SUITABLE_WITH_MODIFICATIONS" && (
          <p className="mt-6 text-sm text-ink-700"><span className="font-semibold">How the agent adapted it: </span>{option.suitability_explanation.replace(/^Template adapted to the client's circumstances: /, "")}</p>
        )}
      </Card>

      <div>
        <h3 className="mb-2 text-xl">Products</h3>
        <p className="mb-5 text-sm text-ink-muted">Past returns, current yield and return assumption measure different things and are shown separately. All products are illustrative data.</p>
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
