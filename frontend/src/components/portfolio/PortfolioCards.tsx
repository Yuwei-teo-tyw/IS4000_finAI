import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { PmOption, PmResponse } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Badge, Button, Card } from "../ui";
import { allocationOf } from "./allocation";
import { AllocationView } from "./AllocationView";
import { DASH, pct, STATUS_LABEL } from "./pmFormat";

const GOAL_LABEL = { ON_TRACK: "on track", SHORTFALL: "shortfall", NOT_ASSESSABLE: "not assessable" } as const;

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-1 text-lg font-light text-ink">{value}</dd>
      {note && <dd className="text-xs text-ink-muted">{note}</dd>}
    </div>
  );
}

function PortfolioCard({ o, preferred, selected, onSelect }: { o: PmOption; preferred: boolean; selected: boolean; onSelect: () => void }) {
  const m = o.metrics;
  return (
    <Card className={`flex h-full flex-col ${selected ? "ring-2 ring-ink" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-ink-muted">Portfolio {o.option_id}</p>
          <h3 className="text-2xl">{o.option_name}</h3>
        </div>
        <span className="flex flex-wrap gap-2">
          {preferred && <Badge tone="navy">Agent's preference</Badge>}
          {selected && <Badge tone="gold">Selected</Badge>}
          <Badge tone="green">{STATUS_LABEL[o.suitability_status]}</Badge>
        </span>
      </div>
      <p className="mt-2 text-sm text-ink-700">{o.objective}</p>

      <div className="mt-6"><AllocationView rows={allocationOf(o)} /></div>

      <dl className="mt-6 grid grid-cols-2 gap-5 border-t border-hairline pt-5 sm:grid-cols-4">
        <Metric label="Risk level" value={o.estimated_risk_level ?? DASH} note={m ? `stress drawdown ${pct(m.estimated_stress_drawdown_pct)}` : undefined} />
        <Metric label="Expected return" value={o.expected_portfolio_return !== null ? `${pct(o.expected_portfolio_return, 2)}` : DASH} note="a year, assumption after fees" />
        <Metric label="Ongoing fees" value={pct(m?.estimated_annual_fee_pct, 2)} note="a year, estimated" />
        <Metric label="Daily dealing" value={pct(m?.high_liquidity_share_pct, 0)} note="of the portfolio" />
      </dl>

      <div className="mt-6 border-t border-hairline pt-5 text-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">How it differs</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-700">{o.key_differences.map((d) => <li key={d}>{d}</li>)}</ul>
      </div>

      <div className="mt-5 grid gap-5 text-sm sm:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Advantages</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-700">{(o.advantages.length ? o.advantages.slice(0, 2) : ["None stated."]).map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Disadvantages</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-700">{(o.disadvantages.length ? o.disadvantages.slice(0, 2) : ["None stated."]).map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      </div>

      <div className="mt-5 text-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Client's goals</p>
        <p className="mt-2 text-ink-700">
          {o.goal_alignment.length ? o.goal_alignment.map((g) => `${g.goal}: ${GOAL_LABEL[g.status]}`).join(" · ") : "No dated goals to assess."}
        </p>
        <p className="mt-4 text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Why it was proposed</p>
        <p className="mt-2 text-ink-700">{o.suitability_explanation}</p>
      </div>

      <div className="mt-auto pt-6">
        {selected ? <Button variant="ghost" disabled>Selected</Button> : <Button variant="ghost" onClick={onSelect}>Select this portfolio</Button>}
      </div>
    </Card>
  );
}

/** The portfolios the agent proposes for this client - however many there are - plus why the rest were not proposed. */
export function PortfolioCards({ response, selected, onSelect }: { response: PmResponse; selected: string | null; onSelect: (id: string) => void }) {
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const offered = response.portfolio_options.filter(isOffered);
  const withdrawn = response.portfolio_options.filter((o) => !isOffered(o));
  return (
    <div className="flex flex-col gap-10">
      <div className="grid gap-8 lg:grid-cols-2">
        {offered.map((o) => (
          <PortfolioCard key={o.option_id} o={o} preferred={response.preferred_option === o.option_id} selected={selected === o.option_id} onSelect={() => onSelect(o.option_id)} />
        ))}
      </div>
      {withdrawn.length > 0 && (
        <Card>
          <button type="button" onClick={() => setShowWithdrawn(!showWithdrawn)} className="flex w-full items-center justify-between text-left" aria-expanded={showWithdrawn}>
            <span>
              <span className="block text-lg text-ink">Not proposed for this client ({withdrawn.length})</span>
              <span className="text-sm text-ink-500">The agent assessed these allocations and left them out. Open to see why.</span>
            </span>
            <ChevronDown className={`transition ${showWithdrawn ? "rotate-180" : ""}`} />
          </button>
          {showWithdrawn && (
            <ul className="mt-6 flex flex-col gap-4 border-t border-ink-200 pt-6 text-sm">
              {withdrawn.map((o) => (
                <li key={o.option_id}><span className="text-ink">{o.option_id} · {o.option_name}:</span> <span className="text-ink-700">{o.suitability_explanation}</span></li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
