import { Badge } from "../../ui";
import { LABEL, SMALL, WRAP } from "./parts";

/** IPS data.market: written by Generate IPS from the Market Analysis Agent (backend market_researcher/ips_context.py). */
export interface IpsMarket {
  status: "ok" | "degraded" | "unavailable"; source: string; runId?: string | null; region?: string; asOf?: string; generatedAt?: string;
  retrievedAt?: string; reusedRun?: boolean; message?: string;
  regime?: { phase?: string | null; confidence?: string | null; recessionProbability?: number | null };
  indicators?: { name: string; value: number; unit: string; date: string; change1y?: number | null; signal?: string | null; stale?: boolean }[];
  themes?: string[]; risks?: string[]; implications?: Record<string, string>; notes?: string[];
}

const when = (s?: string) => (s ? new Date(s).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
const val = (v: number, unit: string) => (unit === "%" ? `${v}%` : `${v} ${unit}`);

/** Read-only: market information belongs to the Market Analysis Agent, not to the RM or PM. */
export function MarketEnvironment({ market }: { market?: IpsMarket | null }) {
  if (!market) return <p className="text-ink-muted" data-testid="ips-market">Market environment: not retrieved. Generate the IPS to fetch it from the Market Analysis Agent.</p>;
  if (market.status === "unavailable") {
    return <p className="text-ink-muted" role="note" data-testid="ips-market">Market environment unavailable from the Market Analysis Agent: {market.message}</p>;
  }
  return (
    <div className="min-w-0 space-y-4" data-testid="ips-market">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={market.status === "ok" ? "green" : "amber"}>{market.source}</Badge>
        <span className={`${SMALL} text-ink-muted`}>Run {market.runId} · {market.region} · data as of {market.asOf} · retrieved {when(market.retrievedAt)}{market.status === "degraded" ? " · incomplete" : ""}</span>
      </div>
      {market.regime?.phase && (
        <p>Economic cycle: {market.regime.phase.replace(/_/g, " ")} (confidence {market.regime.confidence ?? "not stated"}
          {market.regime.recessionProbability != null ? `; probability of being in recession ${Math.round(market.regime.recessionProbability * 1000) / 10}%` : ""}).</p>
      )}
      {!!market.indicators?.length && (
        <table className="w-full table-fixed border-collapse text-left text-[14px]">
          <thead><tr className={`border-b border-hairline ${SMALL} text-ink-muted`}><th className="py-1 pr-2 font-normal">Indicator</th><th className="w-24 py-1 pr-2 text-right font-normal">Latest</th><th className="w-24 py-1 pr-2 text-right font-normal">1y change</th><th className="w-28 py-1 text-right font-normal">Date</th></tr></thead>
          <tbody>
            {market.indicators.map((i) => (
              <tr key={i.name} className="border-b border-hairline"><td className={`py-1 pr-2 ${WRAP}`}>{i.name}{i.stale ? " (stale)" : ""}</td><td className="py-1 pr-2 text-right">{val(i.value, i.unit)}</td>
                <td className="py-1 pr-2 text-right text-ink-muted">{i.change1y != null ? `${i.change1y > 0 ? "+" : ""}${i.change1y}` : "—"}</td><td className="py-1 text-right text-ink-muted">{i.date}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {!!market.themes?.length && <div><p className={LABEL}>Key themes</p><ul className="mt-1 list-disc space-y-1 pl-5">{market.themes.map((t) => <li key={t} className={WRAP}>{t}</li>)}</ul></div>}
      {!!market.risks?.length && <div><p className={LABEL}>Market risks</p><ul className="mt-1 list-disc space-y-1 pl-5">{market.risks.map((t) => <li key={t} className={WRAP}>{t}</li>)}</ul></div>}
      {!!Object.keys(market.implications ?? {}).length && (
        <div><p className={LABEL}>Implications by asset class</p><ul className="mt-1 list-disc space-y-1 pl-5">{Object.entries(market.implications!).map(([k, v]) => <li key={k} className={WRAP}><span className="capitalize">{k}</span>: {v}</li>)}</ul></div>
      )}
      {!!market.notes?.length && <p className={`${SMALL} text-ink-muted`}>{market.notes.join(" ")}</p>}
      <p className={`${SMALL} text-ink-muted`}>Descriptive market information, not advice. It informs the Portfolio Manager's SAA but never overrides the client's profile.</p>
    </div>
  );
}
