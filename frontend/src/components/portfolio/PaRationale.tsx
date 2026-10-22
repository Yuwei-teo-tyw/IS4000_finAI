import type { PaOption, PaResponse, PaStatement } from "../../types/portfolio";
import { Badge, Card, CitationTag } from "../ui";
import { BASIS_LABEL, PHASE_LABEL, pct } from "./paFormat";

function Statements({ items }: { items: PaStatement[] }) {
  if (!items.length) return <p className="text-sm text-ink-muted">None recorded.</p>;
  return (
    <ul className="flex flex-col gap-4">
      {items.map((s, i) => (
        <li key={i} className="flex flex-wrap items-start gap-3 text-sm">
          <Badge tone={s.basis === "FORECAST" || s.basis === "ASSUMPTION" ? "amber" : "grey"}>{BASIS_LABEL[s.basis]}</Badge>
          <span className="min-w-0 flex-1 text-ink-700">{s.statement}{s.source && <span className="ml-1 text-xs text-ink-muted">({s.source})</span>}</span>
        </li>
      ))}
    </ul>
  );
}

/** Why the agent proposed what it did, with every statement labelled by where it comes from. */
export function PaRationale({ response, option }: { response: PaResponse; option: PaOption | undefined }) {
  const es = response.explanation_status;
  const mkt = response.market_context_summary;
  const by = (bases: PaStatement["basis"][]) => (option?.rationale ?? []).filter((s) => bases.includes(s.basis));
  const gaps = response.missing_information.filter((m) => m.severity !== "MINOR");

  return (
    <div className="flex flex-col gap-10">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-xl">{option ? `${option.option_id} · ${option.option_name}` : "Summary"}</h3>
          <Badge tone={es.source === "LLM" ? "navy" : "grey"}>{es.source === "LLM" ? `AI interpretation (${es.model})` : "Calculated summary"}</Badge>
        </div>
        {option?.narrative && <p className="mt-5 max-w-3xl text-[17px] font-light leading-8 text-ink">{option.narrative}</p>}
        <p className="mt-6 max-w-3xl text-sm text-ink-700"><span className="font-semibold">Agent's preference: </span>{response.preferred_option_rationale}</p>
        <p className="mt-4 text-xs text-ink-muted">Numbers come from the calculation engine. {es.detail}</p>
      </Card>

      <div className="grid gap-10 lg:grid-cols-2">
        <Card>
          <h3 className="text-xl">Client limits that shaped it</h3>
          <div className="mt-5"><Statements items={by(["CLIENT_INPUT", "RULE", "CALCULATION"])} /></div>
        </Card>
        <Card>
          <h3 className="text-xl">Market Researcher input</h3>
          <p className="mt-2 text-sm text-ink-muted">
            {mkt.regime?.phase ? `${PHASE_LABEL[mkt.regime.phase] ?? mkt.regime.phase}, ${mkt.regime.confidence} confidence` : "No cycle call"}
            {mkt.regime?.recession_prob_12m != null ? ` · recession probability ${pct(mkt.regime.recession_prob_12m * 100, 0)} in 12 months` : ""}
            {` · as of ${mkt.as_of ?? "n/a"} · ${mkt.data_source_label}`}
          </p>
          <ul className="mt-5 flex flex-col gap-3 text-sm">
            {mkt.events.map((e) => (
              <li key={e.id} className="text-ink-700">{e.description} {e.evidence.map((t) => <CitationTag key={t} tag={t} />)}</li>
            ))}
          </ul>
          {Object.keys(mkt.implications).length > 0 && (
            <ul className="mt-5 flex flex-col gap-2 border-t border-hairline pt-4 text-sm text-ink-700">
              {Object.entries(mkt.implications).map(([area, text]) => <li key={area}><span className="font-semibold capitalize">{area}: </span>{text}</li>)}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <h3 className="text-xl">Assumptions, gaps and warnings</h3>
        <div className="mt-5 grid gap-8 lg:grid-cols-2">
          <ul className="list-disc space-y-2 pl-5 text-sm text-ink-700">
            {[...(option?.assumptions ?? []), ...response.assumptions].map((a, i) => <li key={i}>{a}</li>)}
          </ul>
          <div className="flex flex-col gap-3 text-sm">
            {gaps.map((m) => <p key={m.field}><Badge tone="red">{m.severity.toLowerCase()}</Badge> <span className="text-ink">{m.field}</span>: <span className="text-ink-700">{m.impact}</span></p>)}
            {response.conflicts.map((c, i) => <p key={i}><Badge tone="amber">conflict</Badge> <span className="text-ink-700">{c.description} {c.resolution}</span></p>)}
            {response.warnings.map((w, i) => <p key={i} className="text-ink-muted">{w}</p>)}
          </div>
        </div>
      </Card>
    </div>
  );
}
