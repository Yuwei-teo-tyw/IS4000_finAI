import type { PmOption, PmResponse } from "../../types/portfolio";
import { isOffered } from "../../types/portfolio";
import { Badge, Card } from "../ui";
import { pct, STATUS_LABEL } from "./pmFormat";

export interface SaaTemplate { id: string; name: string; split: number[] }

function Verdict({ o }: { o: PmOption | undefined }) {
  if (!o) return <p className="mt-4 text-sm text-ink-muted">Run the Portfolio Manager to assess this template.</p>;
  if (!isOffered(o) || !o.metrics) {
    return (
      <div className="mt-5 border-t border-hairline pt-4">
        <Badge tone="grey">{STATUS_LABEL[o.suitability_status]}</Badge>
        <p className="mt-3 text-sm text-ink-muted">{o.suitability_explanation}</p>
      </div>
    );
  }
  const m = o.metrics;
  return (
    <div className="mt-5 border-t border-hairline pt-4">
      <Badge tone="green">{STATUS_LABEL[o.suitability_status]}</Badge>
      <dl className="mt-4 grid grid-cols-3 gap-4 text-sm">
        <div><dt className="text-xs text-ink-muted">Expected return</dt><dd className="mt-1 text-lg font-light text-ink">{pct(o.expected_portfolio_return, 2)}</dd></div>
        <div><dt className="text-xs text-ink-muted">Stress drawdown</dt><dd className="mt-1 text-lg font-light text-ink">{pct(m.estimated_stress_drawdown_pct)}</dd></div>
        <div><dt className="text-xs text-ink-muted">Growth assets</dt><dd className="mt-1 text-lg font-light text-ink">{pct(m.growth_asset_share_pct, 0)}</dd></div>
      </dl>
      {o.suitability_status === "SUITABLE_WITH_MODIFICATIONS" && (
        <p className="mt-3 text-xs text-ink-muted">Adapted to the client's limits. See Compare, then Option detail.</p>
      )}
    </div>
  );
}

/** The six SAA templates, each with the Portfolio Manager's verdict. Picking a card is the IC's decision. */
export function TemplateVerdicts({ templates, response, selected, onPick }: {
  templates: SaaTemplate[]; response: PmResponse | null; selected: string; onPick: (id: string) => void;
}) {
  return (
    <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
      {templates.map((t) => {
        const o = response?.portfolio_options.find((x) => x.option_id === t.id);
        return (
          <button key={t.id} type="button" onClick={() => onPick(t.id)} className="text-left" aria-pressed={selected === t.id}>
            <Card className={`h-full ${selected === t.id ? "ring-2 ring-ink" : ""}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-xl">{t.id} · {t.name}</h3>
                <span className="flex gap-2">
                  {response?.preferred_option === t.id && <Badge tone="navy">Agent's preference</Badge>}
                  {selected === t.id && <Badge tone="gold">Selected</Badge>}
                </span>
              </div>
              <p className="mt-4 text-sm text-ink-500">Equities {t.split[2]}% · Fixed income {t.split[1]}% · Cash {t.split[0]}%</p>
              <Verdict o={o} />
            </Card>
          </button>
        );
      })}
    </div>
  );
}
