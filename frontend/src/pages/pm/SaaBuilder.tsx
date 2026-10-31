import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { arcApi, PortfolioAgentError } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, sgdFull, useAsync } from "../../components/ui";
import { InputsPanel } from "../../components/portfolio/InputsPanel";
import { OptionDetail } from "../../components/portfolio/OptionDetail";
import { PaRationale } from "../../components/portfolio/PaRationale";
import { PortfolioCards } from "../../components/portfolio/PortfolioCards";
import { PortfolioCompare } from "../../components/portfolio/PortfolioCompare";
import { ProductCompare } from "../../components/portfolio/ProductCompare";
import { weightsOf } from "../../components/portfolio/allocation";
import { isOffered, PA_BUCKETS, type PaBucketId, type PaBucketInputs, type PaResponse } from "../../types/portfolio";
import { AutoSaveStatus } from "../../components/pm/SaveProgressButton";
import { savePmBucket, usePmProgress, useIpsReturned, type BucketSaa } from "../../services/workflowStore";
import { BackLink, Msg, NumInput } from "./pmHelpers";
import { PM_STEPS } from "./pmSteps";
import { BucketTabs } from "./BucketTabs";
import { bucketStatus, currentStep, isEdited, isUnlocked, nextBucket, selectBucketPortfolio } from "./saaState";

const VIEWS = ["Portfolios", "Compare portfolios"] as const;
const DETAIL = ["Allocation and products", "Why"] as const;
const RISK_LABEL = ["", "Conservative", "Moderately conservative", "Balanced", "Growth", "Aggressive"];
const LIQUIDITY_MAX_YEARS = 3;

type AgentState =
  | { phase: "idle"; note?: string }
  | { phase: "running" }
  | { phase: "done"; response: PaResponse }
  | { phase: "error"; error: PortfolioAgentError };

const isBucket = (b: string | undefined): b is PaBucketId => !!b && (PA_BUCKETS as string[]).includes(b);

/** Step 2 of the IPS SAA request: an SAA for each 3L bucket, built for that bucket's purpose and horizon. */
export default function SaaBuilder() {
  const { clientId = "ser", bucket } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const inputs = useAsync(() => arcApi.getBucketInputs(clientId), [clientId]);
  const progress = usePmProgress(clientId);
  const sent = useIpsReturned(clientId);
  if (!client || !inputs) return <Loading />;
  // Buckets are done in order: an unknown or not-yet-open bucket goes to the step the PM is on.
  if (!isBucket(bucket) || !isUnlocked(inputs, progress.saaBuckets, bucket)) {
    return <Navigate to={`/pm/requests/${clientId}/saa/${currentStep(inputs, progress.saaBuckets)}`} replace />;
  }
  const input = inputs.find((i) => i.id === bucket)!;
  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Strategic asset allocation by bucket"
        subtitle="Each 3L bucket gets its own portfolio, built for what that money is for and when it is needed."
        actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={PM_STEPS} current={sent ? 3 : 1} />
      <BucketTabs clientId={clientId} inputs={inputs} drafts={progress.saaBuckets ?? {}} current={bucket} />
      {/* Remount per bucket: each bucket has its own run, view and selection. */}
      <BucketPanel key={bucket} clientId={clientId} input={input} inputs={inputs} draft={progress.saaBuckets?.[bucket]}
        clientName={client.name} sent={sent} savedAt={progress.savedAt} drafts={progress.saaBuckets ?? {}} />
      <BackLink to={`/pm/requests/${clientId}/3l`}>Back to client profile and 3L</BackLink>
    </div>
  );
}

function BucketPanel({ clientId, input, inputs, draft, drafts, clientName, sent, savedAt }: {
  clientId: string; input: PaBucketInputs; inputs: PaBucketInputs[]; draft?: BucketSaa; drafts: Partial<Record<PaBucketId, BucketSaa>>;
  clientName: string; sent: boolean; savedAt?: string;
}) {
  const navigate = useNavigate();
  const status = bucketStatus(input, draft);
  const [horizon, setHorizon] = useState<number | null>(draft?.horizonYears !== undefined ? draft.horizonYears : input.defaultHorizon);
  const [risk, setRisk] = useState<number | null>(draft?.riskLevel ?? null);
  const [agent, setAgent] = useState<AgentState>({ phase: "idle" });
  const [view, setView] = useState<(typeof VIEWS)[number]>("Portfolios");
  const [detail, setDetail] = useState<(typeof DETAIL)[number]>("Allocation and products");
  const [pendingPick, setPendingPick] = useState<string | null>(null);

  // Coming back to this bucket: reload its proposal from the backend instead of re-running.
  useEffect(() => {
    if (!draft?.requestId) return;
    let live = true;
    setAgent({ phase: "running" });
    arcApi.getPortfolioProposal(draft.requestId)
      .then((r) => { if (live) setAgent({ phase: "done", response: r }); })
      .catch((e) => {
        if (!live) return;
        const expired = e instanceof PortfolioAgentError && e.kind === "NOT_FOUND";
        setAgent(expired ? { phase: "idle", note: `The earlier ${input.label} proposal is no longer on the server (it was restarted). Run the Portfolio Agent again.` }
          : { phase: "error", error: e instanceof PortfolioAgentError ? e : new PortfolioAgentError("SERVER", String(e)) });
      });
    return () => { live = false; };
  }, [draft?.requestId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === "empty") {
    const next = nextBucket(inputs, drafts, input.id);
    return (
      <>
        <Card className="mb-12"><p className="text-ink-700">No money is assigned to the {input.label} bucket on the 3L step, so it needs no SAA.</p></Card>
        <NextAction title={`Nothing to do for ${input.label}`} body="Continue with the next bucket."
          action={<Button variant="gold" onClick={() => navigate(`/pm/requests/${clientId}/saa/${next ?? "review"}`)}>{next ? `Continue to ${next[0].toUpperCase()}${next.slice(1)}` : "Continue to combined review"}</Button>} />
      </>
    );
  }

  const response = agent.phase === "done" ? agent.response : null;
  const offered = response?.portfolio_options.filter(isOffered) ?? [];
  const selectedId = draft?.optionId && offered.some((o) => o.option_id === draft.optionId) ? draft.optionId : null;
  const selected = offered.find((o) => o.option_id === selectedId);
  const draftEdited = isEdited(draft?.weights, draft?.original);
  const settingsChanged = !!draft?.requestId && ((draft.horizonYears ?? null) !== horizon || (draft.riskLevel ?? null) !== risk);
  const stale = status === "stale";
  const blocking = response && offered.length === 0;

  const select = (r: PaResponse, id: string) => {
    const o = r.portfolio_options.find((x) => x.option_id === id);
    if (!o) return;
    selectBucketPortfolio(clientId, input.id, id, o.option_name, weightsOf(o));
    setPendingPick(null);
  };
  const pick = (id: string) => {
    if (!response || id === selectedId) return;
    if (draftEdited && selectedId) setPendingPick(id); // ask before discarding adjusted weights
    else select(response, id);
  };
  const run = async () => {
    if (input.id === "liquidity") return; // Liquidity has no SAA (NA): never call /portfolio/generate for it.
    setAgent({ phase: "running" });
    try {
      const r = await arcApi.generatePortfolioProposals({
        ...input.request,
        request_id: `PM-${clientId}-${input.id}-${Date.now()}`,
        // The goal-based default is left to the agent (so it explains the horizon by the goal); only a PM override is sent.
        bucket: { ...input.request.bucket!, horizon_years: horizon === input.defaultHorizon ? null : horizon, risk_tolerance_score: risk },
      });
      setAgent({ phase: "done", response: r });
      savePmBucket(clientId, input.id, {
        requestId: r.request_id, amount: input.amount, horizonYears: horizon, riskLevel: risk,
        optionId: undefined, optionName: undefined, weights: undefined, original: undefined, confirmed: false,
      });
      if (r.preferred_option) select(r, r.preferred_option);
    } catch (e) {
      setAgent({ phase: "error", error: e instanceof PortfolioAgentError ? e : new PortfolioAgentError("SERVER", String(e)) });
    }
  };

  const horizonNote = input.id === "liquidity"
    ? `Up to ${LIQUIDITY_MAX_YEARS} years: longer-dated money belongs in Longevity or Legacy.`
    : horizon === null ? "Not set. Without a horizon the agent caps growth assets and leaves out long-horizon portfolios."
    : input.defaultHorizon === horizon && input.goals.length ? "From the nearest goal funded by this bucket." : "Set by you.";
  const next = nextBucket(inputs, drafts, input.id);

  return (
    <>
      <Section title={`The ${input.label} bucket`} hint="What this money is for decides how it is invested. Adjust the horizon or risk level before running the agent.">
        <Card>
          <dl className="grid gap-8 md:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Amount</dt>
              <dd className="mt-2 text-2xl font-light text-ink">{sgdFull(input.amount)}</dd>
              <dd className="text-sm text-ink-muted">{input.sharePct}% of the 3L allocation</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Objective</dt>
              <dd className="mt-2 text-ink-700">{input.objective || "Not stated on the 3L step."}</dd>
              <dd className="text-sm text-ink-muted">3L guide: {input.horizonHint}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Investment horizon</dt>
              <dd className="mt-2 flex flex-wrap items-center gap-3">
                <NumInput value={horizon ?? 0} suffix="years" onChange={(n) => setHorizon(n > 0 ? Math.min(n, 100) : null)} />
                {horizon !== null && input.id !== "liquidity" && <Button variant="ghost" size="sm" onClick={() => setHorizon(null)}>Clear</Button>}
              </dd>
              <dd className="mt-2 text-sm text-ink-muted">{horizonNote}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Risk level for this bucket</dt>
              <dd className="mt-2">
                <select value={risk ?? ""} onChange={(e) => setRisk(e.target.value ? Number(e.target.value) : null)} aria-label={`Risk level for the ${input.label} bucket`}
                  className="rounded-md border border-ink-200 bg-surface-100 px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none">
                  <option value="">Client's IPS level ({input.clientRiskLevel} · {RISK_LABEL[input.clientRiskLevel]})</option>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} · {RISK_LABEL[n]}</option>)}
                </select>
              </dd>
              <dd className="mt-2 text-sm text-ink-muted">Use a different level only if the client sees this objective differently. Risk capacity still caps it.</dd>
            </div>
          </dl>
          <div className="mt-8 border-t border-hairline pt-6 text-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Goals this bucket funds</p>
            {input.goals.length
              ? <ul className="mt-2 flex flex-wrap gap-2">{input.goals.map((g) => <li key={g.label}><Badge tone="grey">{g.label} · {g.year} ({g.years < 1 ? "within a year" : `in ${Math.round(g.years)} yrs`})</Badge></li>)}</ul>
              : <p className="mt-2 text-ink-700">No dated goal is assigned to this bucket.</p>}
          </div>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            {agent.phase !== "running" && (
              <Button variant={response && !stale && !settingsChanged ? "ghost" : "primary"} onClick={run}>
                {response ? `Run the Portfolio Agent again for ${input.label}` : `Run the Portfolio Agent for ${input.label}`}
              </Button>
            )}
            {(stale || settingsChanged) && response && (
              <Msg ok={false}>{stale ? `The ${input.label} amount changed on the 3L step after this proposal was built. Run the agent again.` : "You changed the horizon or risk level. Run the agent again to apply it."}</Msg>
            )}
          </div>
          <ClientInputs clientId={clientId} />
        </Card>
      </Section>

      <Section title={`Portfolios for ${input.label}`} hint="The agent builds portfolios for this bucket only, and leaves out any that do not fit its purpose or the client's limits.">
        {agent.phase === "running" && <p className="animate-geneva-flow py-6 text-lg font-light">The Portfolio Agent is preparing {input.label} portfolios for {clientName}…</p>}
        {agent.phase === "idle" && <Msg ok={!agent.note}>{agent.note ?? `Not run yet for ${input.label}.`}</Msg>}
        {agent.phase === "error" && <Msg ok={false}>{agent.error.message}{agent.error.details.length > 0 && ` ${agent.error.details.join(" ")}`}</Msg>}
        {response && <BucketProposal response={response} offered={offered.length} blocking={!!blocking} />}
      </Section>

      {response && !blocking && (
        <>
          <div className="mb-10 flex flex-wrap items-center gap-3" role="tablist" aria-label="Portfolio views">
            {VIEWS.map((v) => (
              <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                className={`rounded-full px-5 py-2 text-sm font-semibold ${view === v ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{v}</button>
            ))}
            <span className="ml-auto flex flex-wrap gap-3">
              {response.preferred_option && response.preferred_option !== selectedId && (
                <Button variant="ghost" size="sm" onClick={() => pick(response.preferred_option!)}>Use the agent's preference ({response.preferred_option})</Button>
              )}
              <Badge tone="grey">{selected ? `Portfolio ${selected.option_id} · ${selected.option_name} selected` : "No portfolio selected"}</Badge>
            </span>
          </div>

          {pendingPick && (
            <div className="mb-10">
              <NextAction title={`Discard your adjusted weights for portfolio ${selectedId}?`}
                body={`You changed portfolio ${selectedId}'s weights for ${input.label}. Selecting portfolio ${pendingPick} starts again from its proposed weights. Other buckets are not affected.`}
                action={<span className="flex gap-3"><Button variant="ghost" onClick={() => setPendingPick(null)}>Keep {selectedId}</Button><Button variant="primary" onClick={() => select(response, pendingPick)}>Discard and select {pendingPick}</Button></span>} />
            </div>
          )}

          {view === "Portfolios" ? (
            <>
              <Section title="Proposed portfolios" hint={`${offered.length} ${offered.length === 1 ? "portfolio fits" : "portfolios fit"} the ${input.label} bucket. Each card shows how it differs from the more cautious one before it.`}>
                <PortfolioCards response={response} selected={selectedId} onSelect={pick} />
              </Section>
              {selected && (
                <Section title={`Portfolio ${selected.option_id} in detail`} hint="Every asset class and product, the checks it passed, and the reasoning behind it.">
                  <div className="mb-8 flex flex-wrap gap-2 border-b border-ink-200" role="tablist" aria-label="Portfolio detail">
                    {DETAIL.map((d) => (
                      <button key={d} type="button" role="tab" aria-selected={detail === d} onClick={() => setDetail(d)}
                        className={`-mb-px border-b-2 px-5 py-3 text-sm font-semibold ${detail === d ? "border-hairline-strong text-ink" : "border-transparent text-ink-500 hover:text-ink"}`}>{d}</button>
                    ))}
                  </div>
                  {detail === "Allocation and products" ? <OptionDetail option={selected} bucketLabel={input.label} /> : <PaRationale response={response} option={selected} />}
                </Section>
              )}
            </>
          ) : (
            <>
              <Section title={`Compare ${input.label} portfolios`} hint="Every asset class held by any proposed portfolio, with risk, return, liquidity, costs and fit with this bucket's goals.">
                <PortfolioCompare response={response} />
              </Section>
              <Section title="Products behind the portfolios" hint="Every candidate from the product recommender, with why it was used or excluded for this bucket.">
                <ProductCompare response={response} />
              </Section>
            </>
          )}
        </>
      )}

      <div className="mb-6 flex justify-end"><AutoSaveStatus savedAt={savedAt} /></div>
      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg>
        : status === "confirmed" && !settingsChanged ? (
          <NextAction title={`${input.label} confirmed`} body={next ? "Continue with the next bucket. You can come back and change this one at any time." : "Every bucket is done. Review all three together."}
            action={<Button variant="gold" onClick={() => navigate(`/pm/requests/${clientId}/saa/${next ?? "review"}`)}>{next ? `Continue to ${next[0].toUpperCase()}${next.slice(1)}` : "Continue to combined review"}</Button>} />
        ) : !response ? (
          <NextAction title={`Run the Portfolio Agent for ${input.label}`} body="Portfolios appear once the agent has assessed this bucket." action={<Button disabled>Continue to Edit weights</Button>} />
        ) : !selected || stale || settingsChanged ? (
          <NextAction title={stale || settingsChanged ? "Run the agent again first" : "Pick a portfolio"}
            body={blocking ? "No portfolio can be proposed for this bucket until the missing information is supplied." : stale || settingsChanged ? "The proposal no longer matches this bucket's amount or settings." : "Select one of the proposed portfolios to continue."}
            action={<Button disabled>Continue to Edit weights</Button>} />
        ) : (
          <NextAction title={`Portfolio ${selected.option_id} · ${selected.option_name} selected for ${input.label}`}
            body={draftEdited ? "You have adjusted weights for this portfolio. Continue to review and confirm them." : "Next, check its weights and confirm them for this bucket."}
            action={<Button variant="gold" onClick={() => navigate(`/pm/requests/${clientId}/saa/${input.id}/weights`)}>Continue to Edit weights</Button>} />
        )}
    </>
  );
}

/** Proposal summary plus how the bucket's purpose shaped it (horizon, risk level, rules applied). */
function BucketProposal({ response, offered, blocking }: { response: PaResponse; offered: number; blocking: boolean }) {
  const b = response.bucket;
  return (
    <div className="flex flex-col gap-6">
      <Msg ok={!blocking}>
        {blocking ? "No portfolio could be proposed for this bucket." : `${offered} ${offered === 1 ? "portfolio" : "portfolios"} proposed.`}{" "}
        Market data: {response.data_status.market_analysis.toLowerCase()}; products: {response.data_status.product_candidates.toLowerCase()}.
      </Msg>
      {b && (
        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">How this bucket shaped the portfolios</p>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-700">
            <li>Horizon: {b.horizon_basis}</li>
            {b.risk_basis && <li>Risk: {b.risk_basis}</li>}
            <li>Templates considered: {b.templates_considered.join(", ")}.</li>
            {b.notes.map((n) => <li key={n.statement}>{n.statement}</li>)}
          </ul>
        </Card>
      )}
      {blocking && (
        <Card>
          <p className="font-semibold text-ink">More information needed</p>
          <ul className="mt-3 flex flex-col gap-3 text-sm">
            {response.missing_information.filter((m) => m.severity !== "MINOR").map((m) => (
              <li key={m.field}><Badge tone="red">{m.severity.toLowerCase()}</Badge> <span className="text-ink">{m.field}</span>: <span className="text-ink-700">{m.impact}</span></li>
            ))}
            {response.conflicts.filter((c) => c.severity !== "INFO").map((c, i) => (
              <li key={i}><Badge tone="amber">conflict</Badge> <span className="text-ink-700">{c.description} {c.resolution}</span></li>
            ))}
            {response.portfolio_options.filter((o) => !isOffered(o)).slice(0, 2).map((o) => (
              <li key={o.option_id} className="text-ink-700">{o.option_id} · {o.option_name}: {o.suitability_explanation}</li>
            ))}
          </ul>
          <p className="mt-6 text-sm text-ink-muted">Ask the RM to update the IPS, or change this bucket's horizon, then run the agent again.</p>
        </Card>
      )}
    </div>
  );
}

/** The whole-client inputs every bucket shares (IPS risk, limits, goals), read-only and collapsed. */
function ClientInputs({ clientId }: { clientId: string }) {
  const [open, setOpen] = useState(false);
  const inputs = useAsync(() => arcApi.getPortfolioInputs(clientId), [clientId]);
  return (
    <div className="mt-8 border-t border-hairline pt-6">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-left" aria-expanded={open}>
        <span className="text-sm font-semibold text-ink">Client profile used for every bucket</span>
        <ChevronDown className={`transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && inputs && <div className="mt-6"><InputsPanel inputs={inputs} /></div>}
    </div>
  );
}
