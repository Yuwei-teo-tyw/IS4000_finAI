import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { arcApi, PortfolioManagerError } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { InputsPanel } from "../../components/portfolio/InputsPanel";
import { OptionDetail } from "../../components/portfolio/OptionDetail";
import { PmRationale } from "../../components/portfolio/PmRationale";
import { PortfolioCards } from "../../components/portfolio/PortfolioCards";
import { PortfolioCompare } from "../../components/portfolio/PortfolioCompare";
import { ProductCompare } from "../../components/portfolio/ProductCompare";
import { weightsOf } from "../../components/portfolio/allocation";
import { sgdAmt } from "../../components/portfolio/pmFormat";
import { isOffered, type PmResponse } from "../../types/portfolio";
import { AutoSaveStatus } from "../../components/ic/SaveProgressButton";
import { saveIcProgress, useIcProgress, useIpsReturned } from "../../services/workflowStore";
import { BackLink, Msg } from "./icHelpers";
import { IC_STEPS } from "./icSteps";
import { isEdited, saveSaaDraft } from "./saaState";

const VIEWS = ["Portfolios", "Compare portfolios"] as const;
const DETAIL = ["Allocation and products", "Why"] as const;

type AgentState =
  | { phase: "idle"; note?: string }
  | { phase: "running" }
  | { phase: "done"; response: PmResponse }
  | { phase: "error"; error: PortfolioManagerError };

/** Step 2 of the IPS SAA request: the Portfolio Manager proposes portfolios; the IC compares and picks one. */
export default function SaaBuilder() {
  const { clientId = "ser" } = useParams();
  const navigate = useNavigate();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const inputs = useAsync(() => arcApi.getPortfolioInputs(clientId), [clientId]);
  const progress = useIcProgress(clientId);
  const sent = useIpsReturned(clientId);
  const [view, setView] = useState<(typeof VIEWS)[number]>("Portfolios");
  const [detail, setDetail] = useState<(typeof DETAIL)[number]>("Allocation and products");
  const [agent, setAgent] = useState<AgentState>({ phase: "idle" });
  const [showInputs, setShowInputs] = useState(true);
  const [pendingPick, setPendingPick] = useState<string | null>(null);

  // Coming back from Edit weights: reload the proposal the backend still holds instead of re-running.
  useEffect(() => {
    if (!progress.pmRequestId || agent.phase !== "idle") return;
    let live = true;
    setAgent({ phase: "running" });
    arcApi.getPortfolioProposal(progress.pmRequestId)
      .then((r) => { if (live) { setAgent({ phase: "done", response: r }); setShowInputs(false); } })
      .catch((e) => {
        if (!live) return;
        const expired = e instanceof PortfolioManagerError && e.kind === "NOT_FOUND";
        setAgent(expired ? { phase: "idle", note: "The earlier proposal is no longer on the server (it was restarted). Run the Portfolio Manager again." }
          : { phase: "error", error: e instanceof PortfolioManagerError ? e : new PortfolioManagerError("SERVER", String(e)) });
      });
    return () => { live = false; };
  }, [progress.pmRequestId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!client || !inputs) return <Loading />;

  const response = agent.phase === "done" ? agent.response : null;
  const offered = response?.portfolio_options.filter(isOffered) ?? [];
  const selectedId = response && progress.saaTemplate && offered.some((o) => o.option_id === progress.saaTemplate) ? progress.saaTemplate : null;
  const selected = offered.find((o) => o.option_id === selectedId);
  const liquidity = inputs.request.client_profile.minimum_cash_reserve ?? null;
  const draftEdited = isEdited(progress.saaWeights, progress.saaOriginal);

  const select = (r: PmResponse, id: string) => {
    const o = r.portfolio_options.find((x) => x.option_id === id);
    if (!o) return;
    const w = weightsOf(o);
    saveSaaDraft(clientId, id, w, w);
    setPendingPick(null);
  };
  const pick = (id: string) => {
    if (!response || id === selectedId) return;
    if (draftEdited && selectedId) setPendingPick(id); // ask before discarding adjusted weights
    else select(response, id);
  };

  const run = async () => {
    setAgent({ phase: "running" });
    try {
      const r = await arcApi.generatePortfolioProposals(inputs.request);
      setAgent({ phase: "done", response: r });
      setShowInputs(false);
      saveIcProgress(clientId, { pmRequestId: r.request_id, saaTemplate: undefined, saaWeights: undefined, saaOriginal: undefined });
      if (r.preferred_option) select(r, r.preferred_option);
    } catch (e) {
      setAgent({ phase: "error", error: e instanceof PortfolioManagerError ? e : new PortfolioManagerError("SERVER", String(e)) });
    }
  };

  const blocking = response && offered.length === 0;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Pick a portfolio" subtitle="The Portfolio Manager proposes portfolios that fit this client. Compare them, pick one, then fine-tune its weights on the next step." actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={IC_STEPS} current={sent ? 3 : 1} />

      <Section title="Portfolio Manager" hint="The agent builds portfolios for this client within the IPS limits and leaves out any that would not fit. You choose.">
        <Card className="mb-8">
          <button type="button" onClick={() => setShowInputs(!showInputs)} className="flex w-full items-center justify-between text-left" aria-expanded={showInputs}>
            <span>
              <span className="block text-lg font-semibold text-ink">Client profile and investment requirements</span>
              <span className="text-sm text-ink-500">
                From the 3L buckets and IPS. Invests {sgdAmt(inputs.request.client_profile.total_aum != null && liquidity != null ? inputs.request.client_profile.total_aum - liquidity : null)}; the Liquidity bucket of {sgdAmt(liquidity)} is held separately.
              </span>
            </span>
            <ChevronDown className={`transition ${showInputs ? "rotate-180" : ""}`} />
          </button>
          {showInputs && <div className="mt-6 border-t border-ink-200 pt-6"><InputsPanel inputs={inputs} /></div>}
        </Card>

        {agent.phase === "running" && <p className="animate-geneva-flow py-6 text-lg font-light">The Portfolio Manager is preparing portfolios for {client.name}…</p>}
        {agent.phase === "error" && (
          <div className="flex flex-col gap-4">
            <Msg ok={false}>{agent.error.message}{agent.error.details.length > 0 && ` ${agent.error.details.join(" ")}`}</Msg>
            <div><Button variant="primary" onClick={run}>Try again</Button></div>
          </div>
        )}
        {agent.phase === "idle" && (
          <div className="flex flex-col gap-4">
            {agent.note && <Msg ok={false}>{agent.note}</Msg>}
            <div><Button variant="primary" onClick={run}>Run the Portfolio Manager</Button></div>
          </div>
        )}
        {response && (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Msg ok={!blocking}>
              {blocking ? "No portfolio could be proposed." : `${offered.length} ${offered.length === 1 ? "portfolio" : "portfolios"} proposed for ${client.name}.`}{" "}
              Market data: {response.data_status.market_analysis.toLowerCase()}; products: {response.data_status.product_candidates.toLowerCase()}.
            </Msg>
            <span className="flex flex-wrap gap-3">
              {response.preferred_option && response.preferred_option !== selectedId && (
                <Button variant="ghost" size="sm" onClick={() => pick(response.preferred_option!)}>Use the agent's preference ({response.preferred_option})</Button>
              )}
              <Button variant="ghost" size="sm" onClick={run}>Run again</Button>
            </span>
          </div>
        )}
      </Section>

      {blocking && (
        <Section title="More information needed" hint="The agent does not invent a portfolio when the profile cannot support one.">
          <Card>
            <ul className="flex flex-col gap-3 text-sm">
              {response.missing_information.filter((m) => m.severity !== "MINOR").map((m) => (
                <li key={m.field}><Badge tone="red">{m.severity.toLowerCase()}</Badge> <span className="text-ink">{m.field}</span>: <span className="text-ink-700">{m.impact}</span></li>
              ))}
              {response.conflicts.filter((c) => c.severity !== "INFO").map((c, i) => (
                <li key={i}><Badge tone="amber">conflict</Badge> <span className="text-ink-700">{c.description} {c.resolution}</span></li>
              ))}
              {response.portfolio_options.filter((o) => !isOffered(o)).slice(0, 1).map((o) => (
                <li key={o.option_id} className="text-ink-700">{o.suitability_explanation}</li>
              ))}
            </ul>
            <p className="mt-6 text-sm text-ink-muted">Ask the RM to update the IPS with these items, then run the Portfolio Manager again.</p>
          </Card>
        </Section>
      )}

      {response && !blocking && (
        <>
          <div className="mb-10 flex flex-wrap items-center gap-3" role="tablist" aria-label="Portfolio views">
            {VIEWS.map((v) => (
              <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                className={`rounded-full px-5 py-2 text-sm font-semibold ${view === v ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{v}</button>
            ))}
            <span className="ml-auto"><Badge tone="grey">{selected ? `Portfolio ${selected.option_id} · ${selected.option_name} selected` : "No portfolio selected"}</Badge></span>
          </div>

          {pendingPick && (
            <div className="mb-10">
              <NextAction title={`Discard your adjusted weights for portfolio ${selectedId}?`}
                body={`You changed portfolio ${selectedId}'s weights on Edit weights. Selecting portfolio ${pendingPick} starts again from its proposed weights.`}
                action={<span className="flex gap-3"><Button variant="ghost" onClick={() => setPendingPick(null)}>Keep {selectedId}</Button><Button variant="primary" onClick={() => select(response, pendingPick)}>Discard and select {pendingPick}</Button></span>} />
            </div>
          )}

          {view === "Portfolios" && (
            <>
              <Section title="Proposed portfolios" hint={`${offered.length} ${offered.length === 1 ? "portfolio fits" : "portfolios fit"} this client's risk profile, goals and limits. Each card shows how it differs from the more cautious one before it.`}>
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
                  {detail === "Allocation and products" ? <OptionDetail option={selected} liquiditySgd={liquidity} /> : <PmRationale response={response} option={selected} />}
                </Section>
              )}
            </>
          )}

          {view === "Compare portfolios" && (
            <>
              <Section title="Compare portfolios" hint="Every asset class held by any proposed portfolio, with risk, return, liquidity, costs and fit with the client's goals.">
                <PortfolioCompare response={response} />
              </Section>
              <Section title="Products behind the portfolios" hint="Every candidate from the Product Specialist, with why it was used or excluded.">
                <ProductCompare response={response} />
              </Section>
            </>
          )}
        </>
      )}

      <div className="mb-6 flex justify-end"><AutoSaveStatus savedAt={progress.savedAt} /></div>
      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg> : !response ? (
        <NextAction title="Run the Portfolio Manager first" body="Portfolios appear once the agent has assessed this client." action={<Button disabled>Continue to Edit weights</Button>} />
      ) : !selected ? (
        <NextAction title="Pick a portfolio" body={blocking ? "No portfolio can be proposed until the missing information is supplied." : "Select one of the proposed portfolios to continue."} action={<Button disabled>Continue to Edit weights</Button>} />
      ) : (
        <NextAction title={`Portfolio ${selected.option_id} · ${selected.option_name} selected`}
          body={draftEdited ? "You have adjusted weights for this portfolio. Continue to review them." : "Next, fine-tune its asset-class weights and see the effect on risk and return."}
          action={<Button variant="gold" onClick={() => navigate(`/ic/requests/${clientId}/saa/weights`)}>Continue to Edit weights</Button>} />
      )}
      <BackLink to={`/ic/requests/${clientId}/3l`}>Back to client profile and 3L</BackLink>
    </div>
  );
}
