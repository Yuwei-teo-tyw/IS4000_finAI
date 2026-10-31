import { useState } from "react";
import { arcApi, PortfolioAgentError } from "../../../services/arcApi";
import { classColor, weightsOf } from "../../portfolio/allocation";
import { Button, sgd } from "../../ui";
import { BulletEditor } from "./edit";
import { Bullets, CELL, EDIT_BOX, IPS_FRAME, LABEL, SMALL, SubHead } from "./parts";
import type { Bucket3L } from "../../../types/arc";
import type { PaBucketInputs } from "../../../types/portfolio";

export type BucketId = "liquidity" | "longevity" | "legacy";
export interface SaaPortfolio { /** Portfolio Agent request id, needed by the combined check. */ requestId?: string; optionId: string; optionName?: string; weights: Record<string, number> }

const TITLES: Record<BucketId, string> = { liquidity: "Liquidity portfolio", longevity: "Longevity portfolio", legacy: "Legacy portfolio" };
const ORDER: BucketId[] = ["liquidity", "longevity", "legacy"];

type Run = { phase: "running" } | { phase: "error"; message: string };

function Pie({ weights, label }: { weights?: Record<string, number>; label: string }) {
  const r = 60, c = 2 * Math.PI * r;
  const rows = Object.entries(weights ?? {}).filter(([, v]) => v > 0);
  const total = rows.reduce((s, [, v]) => s + v, 0) || 1;
  let offset = 0;
  return (
    <svg viewBox="0 0 160 160" className="h-[160px] w-[160px] shrink-0" role="img" aria-label={label}>
      <g transform="rotate(-90 80 80)">
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--scale-track)" strokeWidth="26" />
        {rows.map(([k, v]) => {
          const len = (v / total) * c;
          const el = <circle key={k} cx="80" cy="80" r={r} fill="none" stroke={classColor(k)} strokeWidth="26" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}><title>{`${k} ${v}%`}</title></circle>;
          offset += len;
          return el;
        })}
      </g>
      {!rows.length && <text x="80" y="84" textAnchor="middle" fontSize="12" fill="var(--ink-muted)">No data</text>}
    </svg>
  );
}

export function SaaPortfolios({ clientId, buckets, value, onChange, editable, notes, onNote, noNotes, liquidityNote }: {
  /** PM view: replace the Liquidity card with this one-line note. */ liquidityNote?: string;
  /** Hide the RM explanation column (the PM edits reasons in the IPS strategy boxes). */ noNotes?: boolean;
  clientId: string; buckets: Bucket3L[]; value: Partial<Record<BucketId, SaaPortfolio>>;
  onChange?: (id: BucketId, p: SaaPortfolio) => void; editable: boolean;
  notes?: Partial<Record<BucketId, string>>; onNote?: (id: BucketId, v: string) => void;
}) {
  const [runs, setRuns] = useState<Partial<Record<BucketId, Run>>>({});

  const run = async (id: BucketId) => {
    if (id === "liquidity") return; // Liquidity has no SAA (NA): never call the portfolio generator for it.
    setRuns((s) => ({ ...s, [id]: { phase: "running" } }));
    try {
      const all: PaBucketInputs[] = await arcApi.getBucketInputs(clientId);
      const input = all.find((x) => x.id === id);
      if (!input) throw new PortfolioAgentError("NOT_FOUND", "No inputs for this bucket.");
      // Use the RM's current (possibly edited) 3L numbers, not the saved ones.
      const amount = buckets.find((b) => b.id === id)?.amountSgd ?? input.amount;
      const total = buckets.reduce((s, b) => s + b.amountSgd, 0) || null;
      const reqId = `IPS-${clientId}-${id}-${Date.now()}`;
      const r = await arcApi.generatePortfolioProposals({
        ...input.request,
        request_id: reqId,
        bucket: { ...input.request.bucket!, amount, total_3l_amount: total, horizon_years: null },
      });
      const offered = r.portfolio_options.filter((o) => o.suitability_status === "SUITABLE" || o.suitability_status === "SUITABLE_WITH_MODIFICATIONS");
      const o = offered.find((x) => x.option_id === r.preferred_option) ?? offered[0];
      if (!o) throw new PortfolioAgentError("REJECTED", "The Portfolio Agent returned no suitable portfolio for this bucket.", r.warnings);
      setRuns((s) => ({ ...s, [id]: undefined }));
      onChange?.(id, { requestId: reqId, optionId: o.option_id, optionName: o.option_name, weights: weightsOf(o) });
    } catch (e) {
      setRuns((s) => ({ ...s, [id]: { phase: "error", message: e instanceof Error ? e.message : String(e) } }));
    }
  };

  return (
    <div className="space-y-6">
      {ORDER.map((id) => {
        if (id === "liquidity" && liquidityNote) return null; // the Allocation section carries the one Liquidity note
        const b = buckets.find((x) => x.id === id);
        const p = value[id];
        const st = runs[id];
        const note = notes?.[id] ?? "";
        const lines = note.split("\n").map((l) => l.trim()).filter(Boolean);
        const rows = Object.entries(p?.weights ?? {}).filter(([, v]) => v > 0).sort((a, z) => z[1] - a[1]);
        return (
          <section key={id} className={`@container ${CELL} ${IPS_FRAME}`}>
            <div className="grid min-w-0 grid-cols-1 gap-6 @xl:grid-cols-2">
            <div className="min-w-0">
              <SubHead>{TITLES[id]}</SubHead>
              <p className={`mt-1 ${SMALL} text-ink-muted`}>
                {b ? `${sgd(b.amountSgd)} · ${b.horizon} · ${b.pct}%` : "Not in the 3L allocation"}
              </p>
              <div className="mt-4 flex flex-col items-center gap-4 sm:flex-row sm:items-center">
                <Pie weights={p?.weights} label={`${TITLES[id]} allocation`} />
                <div className="min-w-0 flex-1 self-stretch">
                  {p ? (
                    <>
                      <p className={`${SMALL} text-ink-muted`}>Chosen option: <span className="text-ink">{p.optionName ?? p.optionId}</span></p>
                      <ul className={`mt-2 space-y-1 ${SMALL}`}>
                        {rows.map(([k, v]) => (
                          <li key={k} className="flex items-center gap-2"><i className="inline-block h-3 w-3" style={{ background: classColor(k) }} />{k}<span className="ml-auto">{v}%</span></li>
                        ))}
                      </ul>
                    </>
                  ) : <p className={`${SMALL} text-ink-muted`}>No recommendation yet</p>}
                </div>
              </div>
              {editable && id === "liquidity" && <p className={`mt-4 ${SMALL} text-ink-muted`}>NA: Liquidity has no SAA.</p>}
              {editable && id !== "liquidity" && (
                <div className="mt-4 space-y-2">
                  {st?.phase === "running"
                    ? <p className={`${SMALL} text-ink-muted`} role="status">Geneva is building portfolios…</p>
                    : <Button variant={p ? "secondary" : "primary"} size="sm" onClick={() => run(id)}>{st?.phase === "error" ? "Retry" : "Run Geneva 3L recommendation"}</Button>}
                  {st?.phase === "error" && <p className={`${SMALL} text-ink-700`} role="alert">{st.message}</p>}
                </div>
              )}
            </div>
            {!noNotes && (editable || lines.length > 0) && (
              <div className="min-w-0">
                <p className={LABEL}>RM explanation</p>
                {editable ? (
                  <div className={`mt-2 ${EDIT_BOX}`}>
                    <BulletEditor value={note} onChange={(v) => onNote?.(id, v)} label={`RM explanation, ${TITLES[id]}`} placeholder="Why this allocation suits the client" />
                  </div>
                ) : (
                  <div className="mt-1"><Bullets items={lines} /></div>
                )}
              </div>
            )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
