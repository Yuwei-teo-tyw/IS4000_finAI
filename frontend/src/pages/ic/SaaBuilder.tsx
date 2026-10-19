import { useState } from "react";
import { useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { arcApi, PortfolioManagerError } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, Table, useAsync } from "../../components/ui";
import { InputsPanel } from "../../components/portfolio/InputsPanel";
import { OptionDetail } from "../../components/portfolio/OptionDetail";
import { PmRationale } from "../../components/portfolio/PmRationale";
import { PortfolioCompare } from "../../components/portfolio/PortfolioCompare";
import { ProductCompare } from "../../components/portfolio/ProductCompare";
import { TemplateVerdicts } from "../../components/portfolio/TemplateVerdicts";
import { sgdAmt } from "../../components/portfolio/pmFormat";
import { isOffered, type PmResponse } from "../../types/portfolio";
import { AutoSaveStatus } from "../../components/ic/SaveProgressButton";
import { returnIpsToRm, saveIcProgress, useIcProgress } from "../../services/workflowStore";
import { ASSETS, BackLink, Msg, NumInput, growthLimit, growthShare, sum } from "./icHelpers";
import { IC_STEPS } from "./ThreeLBuilder";

const TABS = ["Template", "Compare", "Edit weights", "Frontier"] as const;
const VIEWS = ["Side by side", "Option detail", "Products", "Why"] as const;

type AgentState =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; response: PmResponse }
  | { phase: "error"; error: PortfolioManagerError };

export default function SaaBuilder() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const templates = useAsync(() => arcApi.getSaaTemplates());
  const inputs = useAsync(() => arcApi.getPortfolioInputs(clientId), [clientId]);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Template");
  const [view, setView] = useState<(typeof VIEWS)[number]>("Side by side");
  // No template until the Portfolio Manager has run; then its preference is pre-selected for the IC to confirm or change.
  const [tid, setTid] = useState<string | null>(null);
  const [vals, setVals] = useState<number[]>([]);
  const progress = useIcProgress(clientId);
  const [sent, setSent] = useState(false);
  const [agent, setAgent] = useState<AgentState>({ phase: "idle" });
  const [showInputs, setShowInputs] = useState(true);
  if (!client || !templates || !inputs) return <Loading />;

  const tpl = templates.find((t) => t.id === tid);
  const pick = (id: string) => { setTid(id); const split = [...templates.find((t) => t.id === id)!.split]; setVals(split); setSent(false); saveIcProgress(clientId, { saaTemplate: id, saa: split }); };
  const total = sum(vals);
  const limit = growthLimit(client.riskCap);
  const growth = growthShare(vals);
  const far = tpl ? ASSETS.filter((_, i) => Math.abs(vals[i] - tpl.split[i]) > 5) : [];
  const totalOk = total === 100, capOk = growth <= limit, bandOk = far.length === 0;
  const valid = totalOk && capOk && bandOk;

  const response = agent.phase === "done" ? agent.response : null;
  const chosen = response?.portfolio_options.find((o) => o.option_id === tid);
  const chosenOffered = !!chosen && isOffered(chosen);
  const liquidity = inputs.request.client_profile.minimum_cash_reserve ?? null;

  const run = async () => {
    setAgent({ phase: "running" });
    try {
      const r = await arcApi.generatePortfolioProposals(inputs.request);
      setAgent({ phase: "done", response: r });
      setShowInputs(false);
      if (r.preferred_option) pick(r.preferred_option);
      else { setTid(null); setVals([]); }
    } catch (e) {
      setAgent({ phase: "error", error: e instanceof PortfolioManagerError ? e : new PortfolioManagerError("SERVER", String(e)) });
    }
  };

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Build the SAA" subtitle="Run the Portfolio Manager, compare templates A to F, then choose and adjust one." actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={IC_STEPS} current={sent ? 2 : 1} />

      <div className="mb-10 flex flex-wrap gap-3">
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)} className={`rounded-full px-5 py-2 text-sm font-semibold ${tab === t ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{t}</button>
        ))}
      </div>

      {tab === "Template" && (
        <>
          <Section title="Portfolio Manager" hint="The agent builds each template into a portfolio for this client, within the IPS limits. You still choose.">
            <Card className="mb-8">
              <button type="button" onClick={() => setShowInputs(!showInputs)} className="flex w-full items-center justify-between text-left">
                <span>
                  <span className="block text-lg font-semibold text-ink">Inputs from the 3L buckets and IPS</span>
                  <span className="text-sm text-ink-500">
                    Invests {sgdAmt(inputs.request.client_profile.total_aum != null && liquidity != null ? inputs.request.client_profile.total_aum - liquidity : null)}. Liquidity bucket of {sgdAmt(liquidity)} is held separately.
                  </span>
                </span>
                <ChevronDown className={`transition ${showInputs ? "rotate-180" : ""}`} />
              </button>
              {showInputs && <div className="mt-6 border-t border-ink-200 pt-6"><InputsPanel inputs={inputs} /></div>}
            </Card>

            {agent.phase === "running" && (
              <p className="animate-geneva-flow py-6 text-lg font-light">The Portfolio Manager is building templates A to F…</p>
            )}
            {agent.phase === "error" && (
              <div className="flex flex-col gap-4">
                <Msg ok={false}>{agent.error.message}{agent.error.details.length > 0 && ` ${agent.error.details.join(" ")}`}</Msg>
                <div><Button variant="primary" onClick={run}>Try again</Button></div>
              </div>
            )}
            {agent.phase === "idle" && <Button variant="primary" onClick={run}>Run the Portfolio Manager</Button>}
            {response && (
              <div className="flex flex-wrap items-center justify-between gap-4">
                <Msg ok>
                  Proposals ready ({response.portfolio_options.filter((o) => o.suitability_status.startsWith("SUITABLE")).length} of 6 templates offered).
                  Market data: {response.data_status.market_analysis.toLowerCase()}, products: {response.data_status.product_candidates.toLowerCase()}.
                </Msg>
                <span className="flex gap-3">
                  {response.preferred_option && response.preferred_option !== tid && (
                    <Button variant="ghost" size="sm" onClick={() => pick(response.preferred_option!)}>Use the agent's preference ({response.preferred_option})</Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={run}>Run again</Button>
                </span>
              </div>
            )}
          </Section>

          {response && (
            <Section title="Pick a template" hint="Templates A to F run from cautious to opportunistic. The agent's view is shown on each; the choice is yours.">
              <TemplateVerdicts templates={templates} response={response} selected={tid ?? ""} onPick={pick} />
            </Section>
          )}
        </>
      )}

      {tab === "Compare" && (
        !response ? (
          <NextAction title="Run the Portfolio Manager first" body="Comparisons use the agent's proposals. Run it from the Template tab." action={<Button variant="primary" onClick={() => setTab("Template")}>Go to Template</Button>} />
        ) : (
          <>
            <div className="mb-10 flex flex-wrap gap-2 border-b border-ink-200">
              {VIEWS.map((v) => (
                <button key={v} type="button" onClick={() => setView(v)}
                  className={`-mb-px border-b-2 px-5 py-3 text-sm font-semibold ${view === v ? "border-hairline-strong text-ink" : "border-transparent text-ink-500 hover:text-ink"}`}>{v}</button>
              ))}
              <span className="ml-auto self-center"><Badge tone="grey">{tid ? `Template ${tid} selected` : "No template selected"}</Badge></span>
            </div>
            {view === "Side by side" && <Section title="Templates side by side" hint="Only templates the agent offers are compared; the others are listed with the reason."><PortfolioCompare response={response} /></Section>}
            {view === "Option detail" && <Section title={tid ? `Template ${tid} in detail` : "Option detail"} hint="Pick a different template on the Template tab to see it here."><OptionDetail option={chosen} templateSplit={tpl?.split ?? []} liquiditySgd={liquidity} /></Section>}
            {view === "Products" && <Section title="Products" hint="Every candidate from the Product Specialist, with why it was used or excluded."><ProductCompare response={response} /></Section>}
            {view === "Why" && <Section title={tid ? `Why: template ${tid}` : "Why"} hint="Each statement is labelled as client input, market observation, forecast, assumption or calculation."><PmRationale response={response} option={chosen} /></Section>}
          </>
        )
      )}

      {(tab === "Edit weights" || tab === "Frontier") && !tpl && (
        <NextAction title="Pick a template first" body="Run the Portfolio Manager on the Template tab; its preferred template is selected for you to confirm or change." action={<Button variant="primary" onClick={() => setTab("Template")}>Go to Template</Button>} />
      )}

      {tab === "Edit weights" && tpl && (
        <Section title="Edit the seven classes" hint={`Template ${tpl.id}. Each class within 5 points of it, total 100, growth assets at most ${limit}% (risk limit ${client.riskCap}).`}>
          <Table head={["Asset class", "Template", "Your SAA", "Gap"]} rows={ASSETS.map((a, i) => {
            const gap = vals[i] - tpl.split[i];
            return [a, `${tpl.split[i]}%`, <NumInput key={a} value={vals[i] ?? 0} suffix="%" onChange={(n) => { const next = vals.map((v, j) => (j === i ? n : v)); setVals(next); saveIcProgress(clientId, { saaTemplate: tid ?? undefined, saa: next }); }} />,
              <span key="g" className={Math.abs(gap) > 5 ? "font-semibold text-negative" : "text-ink-500"}>{gap > 0 ? "+" : ""}{gap}</span>];
          })} />
          <div className="mt-8 flex flex-col gap-4">
            <Msg ok={totalOk}>{totalOk ? "Total is 100." : `Total is ${total}. It must be 100.`}</Msg>
            <Msg ok={capOk}>{capOk ? `Growth assets ${growth}%, inside the ${limit}% limit.` : `Growth assets ${growth}% exceed the ${limit}% limit.`}</Msg>
            <Msg ok={bandOk}>{bandOk ? "All classes within 5 points of the template." : `Too far from template: ${far.join(", ")}.`}</Msg>
          </div>
        </Section>
      )}

      {tab === "Frontier" && tpl && (
        <Section title="Efficient frontier (illustration)" hint="Shows where your mix sits against the best return for each level of risk. Illustrative only.">
          <Card>
            <svg viewBox="0 0 400 240" className="w-full max-w-xl" role="img" aria-label="Efficient frontier">
              <line x1="40" y1="200" x2="380" y2="200" stroke="var(--hairline)" /><line x1="40" y1="20" x2="40" y2="200" stroke="var(--hairline)" />
              <path d="M50 190 Q120 90 380 40" fill="none" stroke="var(--ink)" strokeWidth="3" />
              <circle cx={50 + growth * 4.5} cy={190 - growth * 2.4 + 20} r="8" fill="var(--brand)" stroke="var(--ink)" />
              <text x="210" y="225" textAnchor="middle" fontSize="12" fill="var(--ink-muted)">Risk</text>
              <text x="14" y="110" fontSize="12" fill="var(--ink-muted)" transform="rotate(-90 14 110)">Return</text>
            </svg>
            <p className="mt-4 text-sm text-ink-500">Gold dot = your mix ({growth}% growth assets). Navy line = efficient frontier. Python computes the real curve later.</p>
          </Card>
        </Section>
      )}

      <div className="mb-6 flex justify-end"><AutoSaveStatus savedAt={progress.savedAt} /></div>
      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg> : !response ? (
        <NextAction title="Run the Portfolio Manager first" body="Sending stays off until the agent has assessed templates A to F and a template is selected." action={<Button disabled>Send back to RM</Button>} />
      ) : !tid ? (
        <NextAction title="Pick a template" body="The agent did not nominate a preference. Choose one of the offered templates on the Template tab." action={<Button disabled>Send back to RM</Button>} />
      ) : !chosenOffered ? (
        <NextAction title={`Template ${tid} is not offered by the agent`} body={chosen?.suitability_explanation ?? "Pick one of the offered templates."} action={<Button disabled>Send back to RM</Button>} />
      ) : valid ? (
        <NextAction title="Limit check passed" body="Everything is inside the rules. Send the 3L and SAA back to the RM." action={<Button variant="gold" onClick={() => { setSent(true); returnIpsToRm(clientId); }}>Send back to RM</Button>} />
      ) : (
        <NextAction title="Blocked: fix the checks first" body="Open Edit weights and resolve the red messages. Sending stays off until all three pass." action={<Button disabled>Send back to RM</Button>} />
      )}
      <BackLink to={`/ic/requests/${clientId}/3l`}>Back to 3L</BackLink>
    </div>
  );
}
