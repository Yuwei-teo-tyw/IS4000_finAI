import { useMemo, useState, type ReactNode } from "react";
import type { PaCandidateProduct, PaResponse } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Badge, Table } from "../ui";
import { currentYield, DASH, fx, historical, LIQUIDITY, pct, years } from "./paFormat";

const MAX = 4;

function status(c: PaCandidateProduct) {
  if (c.screening_status === "SELECTED") return <Badge tone="navy">In {c.selected_in_options.join(", ")}</Badge>;
  if (c.screening_status === "EXCLUDED") return <Badge tone="red">Excluded</Badge>;
  return <Badge tone="grey">Eligible, not used</Badge>;
}

function reason(c: PaCandidateProduct) {
  if (c.screening_status === "EXCLUDED") return c.exclusion_reason ?? "Excluded by the client's constraints.";
  if (c.screening_status === "SELECTED") return `Passed every client check; used in option ${c.selected_in_options.join(", ")}.`;
  return "Passed every client check but ranked lower in its asset class, or its asset class was not used.";
}

/** Every product the product recommender supplied, with why it was used or excluded. No scores or rankings are invented. */
export function ProductCompare({ response }: { response: PaResponse }) {
  const options = response.portfolio_options.filter(isOffered);
  const [filter, setFilter] = useState("ALL");
  const [picked, setPicked] = useState<string[]>([]);
  const level = response.client_profile_summary.effective_risk_level;
  const assumption = useMemo(() => {
    const m = new Map<string, number | null>();
    response.portfolio_options.forEach((o) => o.product_selections.forEach((s) => m.set(s.product_id, s.expected_return_assumption)));
    return m;
  }, [response]);

  const all = response.candidate_products;
  const shown = all.filter((c) => (filter === "ALL" ? true : filter === "EXCLUDED" ? c.screening_status === "EXCLUDED" : c.selected_in_options.includes(filter)));
  const compared = all.filter((c) => picked.includes(c.product_id));
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX ? p : [...p, id]));

  const fields: [string, (c: PaCandidateProduct) => ReactNode][] = [
    ["Asset class", (c) => `${c.asset_class}${c.details.sub_asset_class ? ` · ${c.details.sub_asset_class}` : ""}`],
    ["Issuer", (c) => c.details.issuer ?? DASH],
    ["Status for this client", (c) => <div className="flex flex-col gap-2">{status(c)}<span className="text-xs">{reason(c)}</span></div>],
    ["Risk rating", (c) => (c.details.risk_rating !== null ? `${c.details.risk_rating} of 5 (client level ${level ?? "n/a"})` : DASH)],
    ["Past returns · historical", (c) => historical(c.details)],
    ["Current yield · product data", (c) => currentYield(c.details)],
    ["Return assumption · forecast", (c) => { const v = assumption.get(c.product_id); return v !== undefined && v !== null ? pct(v, 2) : <span className="text-xs text-ink-muted">Only formed for products the agent used</span>; }],
    ["Volatility / max drawdown · historical", (c) => `${pct(c.details.volatility)} / ${pct(c.details.maximum_drawdown)}`],
    ["Fees", (c) => `${pct(c.management_fee, 2)} a year, ${pct(c.details.transaction_fee, 2)} dealing`],
    ["Dealing and lock-in", (c) => `${c.liquidity ? LIQUIDITY[c.liquidity] ?? c.liquidity : DASH}${c.details.lock_in_period && c.details.lock_in_period !== "none" ? `, lock-in ${c.details.lock_in_period}` : ""}`],
    ["Duration / maturity", (c) => `${c.details.duration !== null ? `${c.details.duration} yrs` : DASH} / ${c.details.maturity_date ?? DASH}`],
    ["Currency", (c) => fx(c.currency, c.currency_hedged)],
    ["Recommended horizon", (c) => years(c.details.recommended_horizon)],
    ["Minimum investment", (c) => (c.details.minimum_investment !== null ? `S$${c.details.minimum_investment.toLocaleString("en-SG")}` : DASH)],
  ];

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-wrap items-center gap-3">
        {[["ALL", `All products (${all.length})`], ...options.map((o) => [o.option_id, `In option ${o.option_id}`]), ["EXCLUDED", "Excluded"]].map(([k, label]) => (
          <button key={k} type="button" onClick={() => setFilter(k)}
            className={`rounded-full px-5 py-2 text-sm font-semibold ${filter === k ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>
            {label}
          </button>
        ))}
        <span className="ml-auto text-sm text-ink-muted">Tick up to {MAX} to compare side by side.</span>
      </div>

      <Table
        head={["", "Product", "Status", "Risk", "Past returns · historical", "Current yield", "Fee p.a.", "Dealing", "Currency"]}
        rows={shown.map((c) => [
          <input key="c" type="checkbox" aria-label={`Compare ${c.product_name}`} className="h-4 w-4 accent-[var(--ink)]"
            checked={picked.includes(c.product_id)} disabled={!picked.includes(c.product_id) && picked.length >= MAX} onChange={() => toggle(c.product_id)} />,
          <div key="n" className="min-w-[220px]"><p className="text-ink">{c.product_name}</p><p className="text-xs text-ink-muted">{c.product_id} · {c.asset_class}</p></div>,
          <div key="s" className="flex max-w-[240px] flex-col gap-2">{status(c)}{c.exclusion_reason && <span className="text-xs text-ink-muted">{c.exclusion_reason}</span>}</div>,
          <span key="r" className={level !== null && (c.details.risk_rating ?? 0) > level ? "font-semibold text-negative" : ""}>{c.details.risk_rating ?? DASH}</span>,
          historical(c.details),
          currentYield(c.details),
          pct(c.management_fee, 2),
          c.liquidity ? LIQUIDITY[c.liquidity] ?? c.liquidity : DASH,
          fx(c.currency, c.currency_hedged),
        ])}
      />
      <p className="-mt-6 text-xs text-ink-muted">Risk ratings above the client's level ({level ?? "n/a"}) are marked. Fees are shown for information and are not used to rank.</p>

      {compared.length > 0 && (
        <div>
          <div className="mb-5 flex items-center justify-between">
            <h3 className="text-xl">Side by side</h3>
            <button type="button" className="text-sm font-semibold text-ink underline underline-offset-4" onClick={() => setPicked([])}>Clear</button>
          </div>
          <Table
            head={["", ...compared.map((c) => c.product_name)]}
            rows={fields.map(([label, render]) => [<span key="l" className="text-ink-muted">{label}</span>, ...compared.map((c) => <div key={c.product_id} className="min-w-[160px]">{render(c)}</div>)])}
          />
        </div>
      )}
    </div>
  );
}
