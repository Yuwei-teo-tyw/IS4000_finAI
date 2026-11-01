import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { arcApi, PortfolioAgentError } from "../../../services/arcApi";
import { Badge, Button, NumberInput, sgdFull } from "../../ui";
import type { ModelEvaluation, PmModelSaa, SaaBucketId, SaaCheckResponse, SaaRecommendationResponse } from "../../../types/modelSaa";
import { STRAT_COLOR, StrategyDonut } from "./charts";
import { EDIT_BOX, LABEL, SMALL, WRAP } from "./parts";

const TONE = { OK: "green", INCOMPLETE: "amber", UNAVAILABLE: "red" } as const;
const CHECK_TONE = { PASS: "green", WARN: "amber", FAIL: "red" } as const;
const OBJ: Record<string, string> = { preservation: "capital preservation", income: "income", growth: "growth", inflation_protection: "inflation protection", transfer: "wealth transfer", philanthropy: "philanthropy" };
const sum = (w: Record<string, number>) => Math.round(Object.values(w).reduce((s, v) => s + (Number(v) || 0), 0) * 100) / 100;
const pp = (n: number) => (Math.abs(n) < 0.005 ? "0" : `${n > 0 ? "+" : ""}${+n.toFixed(2)}`);
const fmtTime = (s: string | null) => (s ? new Date(s).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

/** The model's weights with the client's excluded classes spread pro rata over the rest (mirrors the backend's agent_weights). */
function withoutExcluded(weights: Record<string, number>, excluded: string[]): Record<string, number> {
  const keep = Object.fromEntries(Object.entries(weights).filter(([k, v]) => !excluded.includes(k) && v > 0));
  const base = sum(keep);
  if (base === 100 || !base) return keep;
  const out = Object.fromEntries(Object.entries(keep).map(([k, v]) => [k, Math.round((v * 10000) / base) / 100]));
  const top = Object.keys(out).sort((a, b) => out[b] - out[a])[0];
  out[top] = Math.round((out[top] + 100 - sum(out)) * 100) / 100;
  return out;
}

export interface SaaStatus { ready: boolean; problems: string[] }

/**
 * PM review, one 3L bucket (Longevity or Legacy): the Portfolio Agent's best-fit model SAA from the bucket's library,
 * built server-side from the client's IPS (Client Profiling Agent), holdings (Client Portfolio Agent), the latest Market
 * Analysis run and the product shelf (Product Specialist). The PM accepts it or picks another suitable model (with a
 * reason), then amends the weights. Nothing here is mock data: an unavailable agent is shown as unavailable.
 */
export function PmSaaBucket({ clientId, bucket, value, onChange, onStatus, editable }: {
  clientId: string; bucket: SaaBucketId; value?: PmModelSaa; onChange: (v: PmModelSaa | undefined) => void;
  onStatus?: (s: SaaStatus) => void; editable: boolean;
}) {
  const [load, setLoad] = useState<{ phase: "loading" } | { phase: "ready"; r: SaaRecommendationResponse } | { phase: "error"; message: string }>({ phase: "loading" });
  const [nonce, setNonce] = useState(0);
  const [checked, setChecked] = useState<{ key: string; res: SaaCheckResponse } | null>(null);
  const [checkErr, setCheckErr] = useState<string | null>(null);
  const [adding, setAdding] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    let live = true;
    setLoad({ phase: "loading" });
    arcApi.getSaaRecommendation(clientId, bucket)
      .then((r) => { if (live) setLoad({ phase: "ready", r }); })
      .catch((e) => { if (live) setLoad({ phase: "error", message: e instanceof PortfolioAgentError ? `${e.message} ${e.details.join(" ")}`.trim() : String(e) }); });
    return () => { live = false; };
  }, [clientId, bucket, nonce]);

  // Debounced backend check of the amended weights; a newer edit cancels the one in flight.
  const weightsKey = value ? JSON.stringify(value.weights) + value.modelId : "";
  useEffect(() => {
    if (!value) { setChecked(null); return; }
    const t = setTimeout(() => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      arcApi.checkSaaWeights(clientId, bucket, value.modelId, value.weights, ctrl.signal)
        .then((c) => { if (!ctrl.signal.aborted) { setChecked({ key: weightsKey, res: c }); setCheckErr(null); } })
        .catch((e) => { if (!ctrl.signal.aborted) { setChecked(null); setCheckErr(e instanceof Error ? e.message : String(e)); } });
    }, 300);
    return () => clearTimeout(t);
  }, [weightsKey, clientId, bucket]); // eslint-disable-line react-hooks/exhaustive-deps

  const r = load.phase === "ready" ? load.r : null;
  const check = checked && checked.key === weightsKey ? checked.res : null;
  const label = bucket === "longevity" ? "Longevity" : "Legacy";
  const rec = r?.recommendation ?? null;
  const total = value ? sum(value.weights) : 0;
  const overrides = !!value && !!rec && value.modelId !== rec.model_id;
  const problems = useMemo(() => {
    if (!value) return [`Choose a ${label} model SAA.`];
    const p: string[] = [];
    if (total !== 100) p.push(`${label} weights add to ${total}%, not 100%.`);
    if (overrides && !value.overrideReason.trim()) p.push(`Give a reason for choosing ${value.modelId} instead of the recommended ${rec?.model_id}.`);
    if (checkErr) p.push(`${label} weights could not be checked: ${checkErr}`);
    else if (!check) p.push(`Checking the ${label} weights…`);
    else if (!check.valid) p.push(`${label} weights fail: ${check.checks.filter((c) => c.status === "FAIL").map((c) => c.detail).join(" ")}`);
    return p;
  }, [value, total, overrides, rec, check, checkErr, label]);
  useEffect(() => { onStatus?.({ ready: problems.length === 0, problems }); }, [problems.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (e: ModelEvaluation) => {
    if (!r) return;
    const isRec = rec?.model_id === e.model_id;
    onChange({
      modelId: e.model_id, modelName: e.model_name, strategy: e.strategy_code, modelWeights: e.weights,
      recommendedModelId: rec?.model_id ?? null, recommendedWeights: rec?.recommended_weights ?? null, recommendationId: r.request_id,
      weights: isRec && rec ? { ...rec.recommended_weights } : withoutExcluded(e.weights, r.client.excluded_asset_classes),
      overrideReason: isRec ? "" : value?.overrideReason ?? "",
    });
  };
  const setW = (k: string, n: number) => value && onChange({ ...value, weights: { ...value.weights, [k]: Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n * 100) / 100)) : 0 } });
  const removeW = (k: string) => value && onChange({ ...value, weights: Object.fromEntries(Object.entries(value.weights).filter(([c]) => c !== k)) });

  if (load.phase === "loading") return <p className="animate-geneva-flow py-4 text-[15px]">The Portfolio Agent is evaluating the {label} model SAAs for this client…</p>;
  if (load.phase === "error") {
    return (
      <div role="alert" className="space-y-3 border-l-2 border-negative pl-3">
        <p className="text-negative">{label} recommendation unavailable. {load.message}</p>
        <p className={`${SMALL} text-ink-muted`}>Nothing is shown in its place. Saved work for this bucket is kept.</p>
        <Button variant="secondary" size="sm" onClick={() => setNonce((n) => n + 1)}><RefreshCw size={14} aria-hidden />Retry</Button>
      </div>
    );
  }
  const res = load.r;
  const classes = Array.from(new Set(res.evaluations.flatMap((e) => Object.keys(e.weights))));
  const rows = value ? Array.from(new Set([...Object.keys(value.modelWeights), ...Object.keys(value.weights)])).sort((a, b) => (value.modelWeights[b] ?? 0) - (value.modelWeights[a] ?? 0)) : [];
  const amount = res.bucket_amount;
  const addable = value ? classes.filter((c) => !(c in value.weights)) : [];
  const recWeights = value && rec && value.modelId === rec.model_id ? rec.recommended_weights : null;

  return (
    <div className="space-y-8" data-testid={`pm-saa-${bucket}`}>
      {/* Where every input came from. */}
      <div className="flex flex-wrap items-center gap-2" aria-label="Data sources">
        <SourceChip status={res.data_status.client_profile} text={`Client profile · ${res.client.ips_basis}`} title="Client Profiling Agent" />
        <SourceChip status={res.data_status.holdings} text={res.client.holdings.available ? "Holdings · Client Portfolio Agent" : `Holdings unavailable`} title={res.client.holdings.message ?? "Client Portfolio Agent"} />
        <SourceChip status={res.market.status} text={res.market.status === "UNAVAILABLE" ? "Market · unavailable" : `Market · run ${res.market.run_id} · as of ${res.market.as_of}`} title={res.market.issues.join(" ") || "Market Analysis Agent"} />
        <SourceChip status={res.products.status} text={`Products · shelf${res.products.as_of ? ` as of ${res.products.as_of}` : ""}`} title="Product Specialist Agent" />
        <button type="button" onClick={() => setNonce((n) => n + 1)} className={`ml-auto inline-flex items-center gap-1 ${SMALL} text-ink-muted hover:text-ink`}><RefreshCw size={13} aria-hidden />Refresh</button>
      </div>
      {res.market.status === "UNAVAILABLE" && <p className={`${SMALL} border-l-2 border-hairline-strong pl-3 text-ink-muted`} role="note">Market Analysis Agent: {res.market.issues.join(" ")}</p>}
      {res.client.missing.length > 0 && <p className={`${SMALL} border-l-2 border-hairline-strong pl-3 text-ink-muted`} role="note">Not in the client's IPS (left blank, not assumed): {res.client.missing.join(", ")}.</p>}

      {/* The agent's recommendation. */}
      <div className="border border-hairline bg-surface-200 px-5 py-4" data-testid="pa-recommendation">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="sky">Portfolio Agent recommendation</Badge>
          <span className={`${SMALL} text-ink-muted`}>{res.bucket_amount !== null ? `${label}: ${sgdFull(res.bucket_amount)} (${res.bucket_pct}% of ${sgdFull(res.client.total_wealth ?? 0)})` : `${label} amount not available`} · generated {fmtTime(res.generated_at)}</span>
        </div>
        {rec ? (
          <>
            <p className="mt-3 text-[17px]">{rec.model_id} · {rec.model_name} <span className="text-ink-muted">· fit {rec.score}/100</span></p>
            <p className={`mt-1 ${WRAP}`}>{rec.summary}</p>
            <p className={`mt-1 ${SMALL} text-ink-muted`} data-testid="decided-by">{rec.decided_by === "llm" ? `Chosen by the Portfolio Agent (${rec.llm_model}) among the models that passed the hard checks; its text was checked against the data.` : `Chosen by the scoring framework. ${rec.llm_note ?? ""}`}</p>
            <Detail title="Why this model">{rec.reasons}</Detail>
            <Detail title="Client information used">{rec.client_factors}</Detail>
            {rec.weight_adjustments.length > 0 && <Detail title="Agent adjustments to the model weights">{rec.weight_adjustments}</Detail>}
            <Detail title="Risks and trade-offs">{rec.risks}</Detail>
            <Detail title="Existing holdings">{rec.existing_holdings}</Detail>
            <Detail title={`Market considerations · ${res.market.source}${res.market.retrieved_at ? `, retrieved ${fmtTime(res.market.retrieved_at)}` : ""}`}>{rec.market_considerations}</Detail>
            {rec.alternatives.length > 0 && (
              <div className="mt-4">
                <p className={LABEL}>Alternatives</p>
                <ul className="mt-1 space-y-2">
                  {rec.alternatives.map((a) => (
                    <li key={a.model_id}><span>{a.model_id} · {a.model_name} <span className="text-ink-muted">· fit {a.score}/100</span></span>
                      <ul className={`mt-1 list-disc pl-5 ${SMALL} text-ink-muted`}>{a.why_not.map((w) => <li key={w}>{w}</li>)}</ul></li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : <p className="mt-3 text-negative" role="alert">{res.no_recommendation_reason}</p>}
        <p className={`mt-4 ${SMALL} text-ink-muted`}>Horizon: {res.horizon_basis}. Objectives ({res.objectives.map((o) => OBJ[o] ?? o).join(", ") || "none"}): {res.objectives_basis}.</p>
      </div>

      {/* Model library for this bucket: reference allocations, not client data. */}
      <div>
        <p className={LABEL}>{label} model library <span className="normal-case tracking-normal">(reference models v{res.library_version})</span></p>
        <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label={`${label} model SAA`}>
          {[...res.evaluations].sort((a, b) => a.risk_level - b.risk_level).map((e) => {
            const on = value?.modelId === e.model_id;
            const isRec = rec?.model_id === e.model_id;
            const cls = `flex min-h-[96px] w-[150px] flex-col justify-between border px-3 py-2 text-left ${on ? "border-2 border-ink bg-surface-100" : "border-hairline-strong bg-surface-100"} ${!e.suitable ? "cursor-not-allowed opacity-50" : editable ? "hover:border-ink" : ""}`;
            const inner = (
              <>
                <span className="text-[14px] leading-5">{e.model_id}<span className="block text-[12px] leading-4 text-ink-muted">{e.model_name}</span></span>
                <span className="mt-1 text-[12px] leading-4">{isRec ? "★ Recommended" : e.suitable ? `Fit ${e.score}/100` : "Not suitable"} · risk {e.risk_level}</span>
              </>
            );
            return editable
              ? <button key={e.model_id} type="button" role="radio" aria-checked={on} aria-disabled={!e.suitable || undefined} data-model={e.model_id}
                  title={e.suitable ? e.purpose : e.unsuitable_reasons.join(" ")} disabled={!e.suitable} onClick={() => choose(e)} className={cls}>{inner}</button>
              : <div key={e.model_id} role="radio" aria-checked={on} aria-disabled="true" data-model={e.model_id} className={cls}>{inner}</div>;
          })}
        </div>
        {editable && rec && value?.modelId !== rec.model_id && (
          <div className="mt-3"><Button variant="secondary" size="sm" onClick={() => choose(res.evaluations.find((e) => e.model_id === rec.model_id)!)}>Accept the recommended model ({rec.model_id})</Button></div>
        )}
        <Collapsible title="All models evaluated and the scoring method">
          <p className={`${SMALL} ${WRAP}`}>{res.methodology}</p>
          <ul className="mt-2 space-y-2">
            {res.evaluations.map((e) => (
              <li key={e.model_id} className={SMALL}>
                <span className="text-ink">{e.model_id} {e.model_name}</span> · {e.suitable ? `${e.score}/100${e.rank ? `, rank ${e.rank}` : ""}` : "not suitable"}
                <span className="block text-ink-muted">{e.suitable ? e.criteria.map((c) => `${c.label} ${c.score}/${c.max}`).join(" · ") : e.unsuitable_reasons.join(" ")}</span>
              </li>
            ))}
          </ul>
        </Collapsible>
      </div>

      {value && (
        <>
          {overrides && (
            <div>
              <label htmlFor={`override-${bucket}`} className={LABEL}>Reason for choosing {value.modelId} instead of {rec?.model_id}</label>
              {editable
                ? <textarea id={`override-${bucket}`} rows={3} value={value.overrideReason} onChange={(e) => onChange({ ...value, overrideReason: e.target.value })}
                    className={`mt-1 block w-full px-2 py-2 text-[15px] leading-6 ${EDIT_BOX}`} placeholder="Why this model suits the client better than the recommendation" />
                : <p className={`mt-1 ${WRAP}`}>{value.overrideReason || "No reason recorded."}</p>}
              {editable && !value.overrideReason.trim() && <p role="alert" className={`mt-1 ${SMALL} text-negative`}>A reason is required; it is logged with the override.</p>}
            </div>
          )}
          <div className="grid min-w-0 grid-cols-1 gap-8 @3xl:grid-cols-[minmax(0,1fr)_220px]">
            <div className="min-w-0 overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-left text-[14px]" data-testid={`saa-weights-${bucket}`}>
                <thead>
                  <tr className={`border-b border-hairline ${SMALL} text-ink-muted`}>
                    <th className="py-2 pr-2 font-normal">Asset class</th>
                    <th className="py-2 pr-2 text-right font-normal">Model {value.modelId}</th>
                    <th className="py-2 pr-2 text-right font-normal">Agent</th>
                    <th className="py-2 pr-2 text-right font-normal">PM amended</th>
                    <th className="py-2 pr-2 text-right font-normal">vs model</th>
                    <th className="py-2 pr-2 text-right font-normal">Amount</th>
                    {editable && <th className="py-2 font-normal"><span className="sr-only">Remove</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((k) => {
                    const m = value.modelWeights[k] ?? 0, w = value.weights[k];
                    return (
                      <tr key={k} className="border-b border-hairline align-middle">
                        <td className="py-2 pr-2"><i className="mr-2 inline-block h-2.5 w-2.5" style={{ background: STRAT_COLOR[k] ?? "var(--ink-muted)" }} aria-hidden />{k}</td>
                        <td className="py-2 pr-2 text-right">{m}%</td>
                        <td className="py-2 pr-2 text-right text-ink-muted">{recWeights ? `${recWeights[k] ?? 0}%` : "—"}</td>
                        <td className="py-2 pr-2 text-right">
                          {editable && w !== undefined
                            ? <NumberInput step="0.5" min={0} max={100} value={w} aria-label={`${label} ${k} percent`} onChange={(e) => setW(k, Number(e.target.value))}
                                className={`w-20 px-1 py-0.5 text-right ${EDIT_BOX}`} />
                            : `${w ?? 0}%`}
                        </td>
                        <td className={`py-2 pr-2 text-right ${Math.abs((w ?? 0) - m) > 0.005 ? "text-ink" : "text-ink-muted"}`}>{pp((w ?? 0) - m)}</td>
                        <td className="py-2 pr-2 text-right text-ink-muted">{amount ? sgdFull(Math.round((amount * (w ?? 0)) / 100)) : "—"}</td>
                        {editable && <td className="py-2 text-right">{w !== undefined && <button type="button" onClick={() => removeW(k)} className={`${SMALL} text-ink-muted underline hover:text-ink`} aria-label={`Remove ${k}`}>Remove</button>}</td>}
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td className="py-2 pr-2">Total</td><td className="py-2 pr-2 text-right">100%</td><td />
                    <td className={`py-2 pr-2 text-right ${total === 100 ? "" : "text-negative"}`} data-testid={`saa-total-${bucket}`}>{total}%</td>
                    <td /><td className="py-2 pr-2 text-right text-ink-muted">{amount ? sgdFull(Math.round((amount * total) / 100)) : "—"}</td>{editable && <td />}
                  </tr>
                </tfoot>
              </table>
              {editable && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  {addable.length > 0 && (
                    <>
                      <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label={`Add an asset class to ${label}`} className={`px-2 py-1 text-[14px] ${EDIT_BOX}`}>
                        <option value="">Add an asset class…</option>
                        {addable.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <Button variant="secondary" size="sm" disabled={!adding} onClick={() => { onChange({ ...value, weights: { ...value.weights, [adding]: 0 } }); setAdding(""); }}>Add</Button>
                    </>
                  )}
                  <Button variant="ghost" size="sm" disabled={JSON.stringify(value.weights) === JSON.stringify(recWeights ?? withoutExcluded(value.modelWeights, res.client.excluded_asset_classes))}
                    onClick={() => onChange({ ...value, weights: { ...(recWeights ?? withoutExcluded(value.modelWeights, res.client.excluded_asset_classes)) } })}>Reset weights</Button>
                </div>
              )}
              <ul className="mt-4 space-y-1" aria-live="polite" data-testid={`saa-checks-${bucket}`}>
                {checkErr && <li className={`${SMALL} text-negative`}>The weights could not be checked: {checkErr}</li>}
                {check?.checks.map((c) => (
                  <li key={c.id} className={`flex flex-wrap items-center gap-2 ${SMALL}`}><Badge tone={CHECK_TONE[c.status]}>{c.status.toLowerCase()}</Badge><span>{c.label}</span><span className="text-ink-muted">{c.detail}</span></li>
                ))}
              </ul>
              {check && (
                <p className={`mt-2 ${SMALL} text-ink-muted`}>
                  Growth assets {check.metrics.growth_share_pct}% · illiquid {check.metrics.illiquid_share_pct}%
                  {check.metrics.long_term_return_pct !== null && ` · long-term return ${check.metrics.long_term_return_pct}% a year`}
                  {check.metrics.recession_return_pct !== null && ` · recession scenario ${check.metrics.recession_return_pct}%`}
                  {check.metrics.assumptions_label && ` (${check.metrics.assumptions_label}; not a forecast)`}.
                </p>
              )}
            </div>
            <StrategyDonut allocation={value.weights} label={`${label} SAA, PM amended weights`} hideLegend />
          </div>
          <Products res={res} weights={value.weights} />
        </>
      )}
    </div>
  );
}

function SourceChip({ status, text, title }: { status: string; text: string; title: string }) {
  return <span title={title} className="inline-flex"><Badge tone={TONE[status as keyof typeof TONE] ?? "grey"}>{text}</Badge></span>;
}

function Detail({ title, children }: { title: string; children: string[] }) {
  if (!children.length) return null;
  return (
    <div className="mt-4">
      <p className={LABEL}>{title}</p>
      <ul className={`mt-1 list-disc space-y-1 pl-5 ${WRAP}`}>{children.map((c) => <li key={c}>{c}</li>)}</ul>
    </div>
  );
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="mt-4">
      <summary className={`cursor-pointer ${SMALL} text-ink-muted hover:text-ink`}>{title}</summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

/** Products from the Product Specialist's shelf for the classes in the amended allocation, within the client's risk level. */
function Products({ res, weights }: { res: SaaRecommendationResponse; weights: Record<string, number> }) {
  const p = res.products;
  const held = Object.keys(weights).filter((k) => weights[k] > 0);
  return (
    <Collapsible title={`Products to implement this allocation · ${p.source}${p.as_of ? `, shelf as of ${p.as_of}` : ""}`}>
      {p.status === "UNAVAILABLE" ? <p className={`${SMALL} text-negative`}>{p.issues.join(" ") || "The product shelf is unavailable."}</p> : (
        <div className="space-y-3">
          {held.map((ac) => {
            const items = p.by_asset_class[ac];
            return (
              <div key={ac}>
                <p className={`${SMALL} text-ink`}>{ac}</p>
                {items?.length ? (
                  <ul className={`mt-1 space-y-1 ${SMALL} text-ink-muted`}>
                    {items.map((x) => (
                      <li key={x.product_id}>{x.product_name} ({x.product_id}) · risk {x.risk_rating ?? "n/a"}
                        {x.return_3y_pct !== null && ` · 3y ${x.return_3y_pct}%`}{x.management_fee_pct !== null && ` · fee ${x.management_fee_pct}%`}
                        {x.liquidity && ` · ${x.liquidity.toLowerCase()} dealing`}{x.lock_in && x.lock_in !== "none" && ` · lock-in ${x.lock_in}`}{x.note && ` · ${x.note}`}</li>
                    ))}
                  </ul>
                ) : <p className={`${SMALL} text-ink-muted`}>No product on the shelf within the client's risk level for this class.</p>}
              </div>
            );
          })}
          {p.issues.map((i) => <p key={i} className={`${SMALL} text-ink-muted`}>{i}</p>)}
        </div>
      )}
    </Collapsible>
  );
}
