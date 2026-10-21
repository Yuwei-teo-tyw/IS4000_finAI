import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi, PortfolioManagerError } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { FrontierChart } from "../../components/portfolio/FrontierChart";
import { classColor, weightsOf } from "../../components/portfolio/allocation";
import { DASH, pct, sgdAmt } from "../../components/portfolio/pmFormat";
import { isOffered, type PmOption, type PmPortfolioPoint, type PmWeightEvaluation } from "../../types/portfolio";
import { AutoSaveStatus } from "../../components/ic/SaveProgressButton";
import { returnIpsToRm, useIcProgress, useIpsReturned } from "../../services/workflowStore";
import { BackLink, Msg, NumInput } from "./icHelpers";
import { IC_STEPS } from "./icSteps";
import { isEdited, saveSaaDraft } from "./saaState";

const DEBOUNCE_MS = 250;
const CHECK_TONE = { PASS: "green", FAIL: "red", UNVERIFIED: "amber", NOT_APPLICABLE: "grey" } as const;

type Load = { phase: "loading" } | { phase: "missing"; reason: string } | { phase: "ready"; option: PmOption; requestId: string };

/** Step 3 of the IPS SAA request: adjust the selected portfolio's weights beside its risk-return position. */
export default function SaaWeights() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const progress = useIcProgress(clientId);
  const sent = useIpsReturned(clientId);
  const [load, setLoad] = useState<Load>({ phase: "loading" });

  useEffect(() => {
    if (!progress.pmRequestId || !progress.saaTemplate) {
      setLoad({ phase: "missing", reason: "No portfolio has been selected yet." });
      return;
    }
    let live = true;
    arcApi.getPortfolioProposal(progress.pmRequestId).then((r) => {
      if (!live) return;
      const o = r.portfolio_options.find((x) => x.option_id === progress.saaTemplate);
      setLoad(o && isOffered(o) ? { phase: "ready", option: o, requestId: r.request_id }
        : { phase: "missing", reason: `Portfolio ${progress.saaTemplate} is not part of the current proposal.` });
    }).catch((e) => {
      if (!live) return;
      setLoad({ phase: "missing", reason: e instanceof PortfolioManagerError && e.kind === "NOT_FOUND"
        ? "The proposal is no longer on the server (it was restarted). Go back and run the Portfolio Manager again."
        : e instanceof PortfolioManagerError ? e.message : String(e) });
    });
    return () => { live = false; };
  }, [progress.pmRequestId, progress.saaTemplate]);

  if (!client || load.phase === "loading") return <Loading />;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Edit portfolio weights"
        subtitle={load.phase === "ready" ? `Portfolio ${load.option.option_id} · ${load.option.option_name}. Adjust each asset class; risk and return update as you go.` : undefined}
        actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={IC_STEPS} current={sent ? 3 : 2} />
      {load.phase === "missing" ? (
        <>
          <NextAction title="Pick a portfolio first" body={load.reason} action={<Button variant="primary" to={`/ic/requests/${clientId}/saa`}>Back to Pick a portfolio</Button>} />
          <BackLink to={`/ic/requests/${clientId}/saa`}>Back to Pick a portfolio</BackLink>
        </>
      ) : (
        <WeightEditor clientId={clientId} requestId={load.requestId} option={load.option} sent={sent} savedAt={progress.savedAt}
          initial={progress.saaWeights && sameClasses(progress.saaWeights, weightsOf(load.option)) ? progress.saaWeights : weightsOf(load.option)} />
      )}
    </div>
  );
}

const sameClasses = (a: Record<string, number>, b: Record<string, number>) =>
  Object.keys(a).length === Object.keys(b).length && Object.keys(b).every((k) => k in a);

function WeightEditor({ clientId, requestId, option, initial, sent, savedAt }: {
  clientId: string; requestId: string; option: PmOption; initial: Record<string, number>; sent: boolean; savedAt?: string;
}) {
  const original = useMemo(() => weightsOf(option), [option]);
  const classes = useMemo(() => Object.keys(original).sort((a, b) => original[b] - original[a]), [original]);
  const navigate = useNavigate();
  const [weights, setWeights] = useState<Record<string, number>>(initial);
  const [evaluation, setEvaluation] = useState<PmWeightEvaluation | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<PortfolioManagerError | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Debounced backend re-check; a newer change cancels the request in flight.
  useEffect(() => {
    setPending(true);
    const t = setTimeout(() => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      arcApi.evaluatePortfolioWeights(requestId, option.option_id, weights, ctrl.signal)
        .then((e) => { if (!ctrl.signal.aborted) { setEvaluation(e); setError(null); setPending(false); } })
        .catch((e) => { if (!ctrl.signal.aborted) { setError(e instanceof PortfolioManagerError ? e : new PortfolioManagerError("SERVER", String(e))); setPending(false); } });
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [weights, requestId, option.option_id]);
  useEffect(() => () => abort.current?.abort(), []);

  const change = (ac: string, v: number) => {
    const next = { ...weights, [ac]: Number.isFinite(v) ? v : 0 };
    setWeights(next);
    saveSaaDraft(clientId, option.option_id, next, original); // autosaved draft; Back keeps it
  };
  const reset = () => { setWeights(original); saveSaaDraft(clientId, option.option_id, original, original); };
  const total = classes.reduce((s, c) => s + (weights[c] ?? 0), 0);
  const edited = isEdited(weights, original);
  const line = (ac: string) => evaluation?.lines.find((l) => l.asset_class === ac);
  const checks = evaluation?.checks.filter((c) => c.status !== "NOT_APPLICABLE") ?? [];
  const canSend = !!evaluation && evaluation.valid && !pending && !error;

  return (
    <>
      <div className="mb-14 grid gap-10 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Section title="Asset-class weights" hint="Each class may move up to 5 points from the proposal. Other weights never change on their own.">
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-ink-muted">
                  <tr className="border-b border-hairline">
                    <th className="py-3 pr-4 font-semibold">Asset class</th>
                    <th className="py-3 pr-4 text-right font-semibold">Proposed</th>
                    <th className="py-3 pr-4 font-semibold">Your weight</th>
                    <th className="py-3 pr-4 text-right font-semibold">Change</th>
                    <th className="py-3 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {classes.map((ac) => {
                    const l = line(ac);
                    const d = (weights[ac] ?? 0) - original[ac];
                    return (
                      <tr key={ac} className="border-b border-hairline align-top">
                        <td className="py-4 pr-4">
                          <span className="inline-flex items-center gap-2 text-ink"><i className="inline-block h-2.5 w-2.5" style={{ background: classColor(ac) }} aria-hidden />{ac}</span>
                          <p className="mt-1 text-xs text-ink-muted">
                            Return {pct(l?.expected_return_pct, 2)} · drawdown {pct(l?.stress_drawdown_pct)} · volatility {pct(l?.model_volatility_pct)}
                          </p>
                        </td>
                        <td className="py-4 pr-4 text-right text-ink">{pct(original[ac], 2)}</td>
                        <td className="py-4 pr-4"><NumInput value={weights[ac] ?? 0} suffix="%" onChange={(n) => change(ac, n)} /></td>
                        <td className={`py-4 pr-4 text-right ${Math.abs(d) > 5 + 1e-9 ? "font-semibold text-negative" : "text-ink-500"}`}>{Math.abs(d) < 1e-9 ? "0" : `${d > 0 ? "+" : ""}${+d.toFixed(2)}`}</td>
                        <td className="py-4 text-right text-ink-700">{l ? sgdAmt(l.adjusted_amount) : DASH}</td>
                      </tr>
                    );
                  })}
                  <tr className="font-semibold">
                    <td className="py-4 pr-4 text-ink">Total</td>
                    <td className="py-4 pr-4 text-right text-ink">100%</td>
                    <td className={`py-4 pr-4 ${Math.abs(total - 100) > 0.01 ? "text-negative" : "text-positive"}`}>{+total.toFixed(2)}%</td>
                    <td colSpan={2} className="py-4 text-right text-ink-700">{sgdAmt(option.eligible_portfolio_value)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
              <p className="text-xs text-ink-muted">Return and drawdown per class come from the selected products; volatility is a house assumption.</p>
              <Button variant="ghost" size="sm" onClick={reset} disabled={!edited}>Reset to original weights</Button>
            </div>
          </Card>

          <div className="mt-8 flex flex-col gap-3" aria-live="polite">
            {pending && <p className="text-sm text-ink-muted">Checking the adjusted portfolio…</p>}
            {error && <Msg ok={false}>{error.message} {error.details.join(" ")}</Msg>}
            {!error && checks.map((c) => (
              <p key={c.constraint} className="flex flex-wrap items-center gap-3 text-sm">
                <Badge tone={CHECK_TONE[c.status]}>{c.status.replace("_", " ").toLowerCase()}</Badge>
                <span className="text-ink">{c.constraint}</span>
                <span className="text-ink-muted">{c.detail}{c.actual !== null && c.limit !== null ? ` (${+c.actual.toFixed(2)} vs limit ${c.limit})` : ""}</span>
              </p>
            ))}
          </div>
        </Section>

        <Section title="Risk and return" hint="Where the proposed and adjusted portfolios sit against the efficient frontier for the classes this client can hold.">
          <Card>
            {evaluation ? (
              <>
                <FrontierChart frontier={evaluation.frontier} original={evaluation.original} adjusted={evaluation.adjusted} limitation={evaluation.frontier_limitation} />
                <MetricsTable original={evaluation.original} adjusted={evaluation.adjusted} />
                <div className="mt-6 space-y-1 text-xs text-ink-muted">
                  {evaluation.frontier && <p>Model: {evaluation.frontier.model_label}. {evaluation.frontier.method}</p>}
                  {evaluation.notes.map((n) => <p key={n}>{n}</p>)}
                  <p>Figures are calculated from illustrative assumptions and illustrative product data; they are not guarantees.</p>
                </div>
              </>
            ) : (
              <p className="py-16 text-center text-sm text-ink-muted">{error ? "No risk and return figures until the check succeeds." : "Calculating…"}</p>
            )}
          </Card>
        </Section>
      </div>

      <div className="mb-6 flex justify-end"><AutoSaveStatus savedAt={savedAt} /></div>
      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg> : canSend ? (
        <NextAction title="All checks passed" body={edited ? "Your adjusted weights are inside every limit. Continue to send the 3L and SAA back to the RM." : "The proposed weights are inside every limit. Continue to send the 3L and SAA back to the RM."}
          action={<Button variant="gold" onClick={() => { saveSaaDraft(clientId, option.option_id, weights, original); returnIpsToRm(clientId); navigate("/ic/inbox"); }}>Continue: send back to RM</Button>} />
      ) : (
        <NextAction title={pending ? "Checking…" : "Blocked: fix the checks first"} body={error ? "The weights could not be checked." : "Resolve the red checks above, or reset to the original weights. Sending stays off until every check passes."}
          action={<Button disabled>Continue: send back to RM</Button>} />
      )}
      <div className="flex flex-wrap items-center gap-6">
        <BackLink to={`/ic/requests/${clientId}/saa`}>Back to Pick a portfolio</BackLink>
        {edited && <p className="mb-10 text-sm text-ink-muted">Your adjusted weights are saved as a draft and will be here when you return.</p>}
      </div>
    </>
  );
}

function MetricsTable({ original, adjusted }: { original: PmPortfolioPoint; adjusted: PmPortfolioPoint }) {
  const rows: [string, (p: PmPortfolioPoint) => string, string][] = [
    ["Volatility (model)", (p) => pct(p.model_volatility_pct), "House assumptions"],
    ["Expected return (model, before fees)", (p) => pct(p.model_expected_return_pct, 2), "House assumptions"],
    ["Expected return (products, after fees)", (p) => pct(p.product_expected_return_pct, 2), "Product yields and house assumptions"],
    ["Stress drawdown", (p) => pct(p.stress_drawdown_pct), "Products' worst historical drawdowns"],
    ["Growth assets", (p) => pct(p.growth_asset_share_pct), "Equities, hedge funds, private markets"],
    ["Ongoing fees", (p) => pct(p.estimated_annual_fee_pct, 2), "Product management fees"],
    ["Unhedged foreign currency", (p) => pct(p.foreign_currency_exposure_pct), "Products"],
  ];
  return (
    <table className="mt-8 w-full text-left text-sm">
      <thead className="text-xs text-ink-muted">
        <tr className="border-b border-hairline"><th className="py-2 font-semibold">Measure</th><th className="py-2 text-right font-semibold">Proposed</th><th className="py-2 text-right font-semibold">Adjusted</th></tr>
      </thead>
      <tbody>
        {rows.map(([label, get, basis]) => {
          const a = get(original), b = get(adjusted);
          return (
            <tr key={label} className="border-b border-hairline">
              <td className="py-2 pr-4"><span className="text-ink">{label}</span><span className="block text-xs text-ink-muted">{basis}</span></td>
              <td className="py-2 text-right text-ink-700">{a}</td>
              <td className={`py-2 text-right ${a !== b ? "font-semibold text-ink" : "text-ink-700"}`}>{b}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
