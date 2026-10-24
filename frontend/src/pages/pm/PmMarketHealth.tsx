import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { BulletTextarea, Button, CitationTag, GateChip, Loading, NextAction, PageHeader, Section, toBulletItems, useAsync } from "../../components/ui";
import { AutoSaveStatus } from "../../components/pm/SaveProgressButton";
import { loadPackDrafts, savePackDraft } from "../../services/packDraftStore";
import { PmStepper } from "../../components/pm/PmStepper";
import { TaaPie } from "../../components/pm/TaaPie";
import { usePmProgress } from "../../services/workflowStore";
import { composeBlocks, parseBlocks } from "../../services/packBlocks";
import { BackLink, splitCitations } from "./pmHelpers";

interface Topic { heading: string; help: string; keys: RegExp }
const TOPICS: Record<number, Topic[]> = {
  2: [
    { heading: "Current regime", help: "Where we are in the cycle: growth, inflation, policy rates.", keys: /regime|growth|expansion|policy|rate/i },
    { heading: "CIO house view", help: "The CIO stance by asset class, with the CIO source tag.", keys: /CIO|stance|valuation/i },
    { heading: "Misc notes", help: "Anything else the RM should know before the client meeting.", keys: /./ },
  ],
  3: [
    { heading: "Industry related", help: "Sector and industry concentrations that matter now.", keys: /sector|technology|industry|concentrat/i },
    { heading: "Diversification", help: "Spread across asset classes, regions and holdings.", keys: /diversif|score|together|exposure/i },
    { heading: "Strengths", help: "What is working well for this client.", keys: /sharpe|within|strong/i },
    { heading: "Weaknesses", help: "Weaknesses and risks: where the portfolio is exposed or inefficient, and what could hurt it.", keys: /weak|drag|lag|cash yield|margin/i },
  ],
};
const TITLES: Record<number, string> = { 2: "Market view", 3: "Portfolio current health" };

/** Seed topic fields from a saved block body, or distribute legacy bullets by keyword. */
function seed(n: number, body: string): Record<string, string> {
  const topics = TOPICS[n];
  const parsed = parseBlocks(body).filter((b) => b.heading).map((b): [string, string] => [b.heading as string, b.text]);
  const out: Record<string, string> = Object.fromEntries(topics.map((t) => [t.heading, ""]));
  if (parsed.length) {
    parsed.forEach(([h, t]) => { if (h in out) out[h] = t; });
    // Legacy "Risks" block is merged into Weaknesses.
    const risks = parsed.filter(([h]) => h === "Risks").map(([, t]) => t.trim()).filter(Boolean).join("\n");
    if (risks && "Weaknesses" in out) out.Weaknesses = [out.Weaknesses.trim(), risks].filter(Boolean).join("\n");
    return out;
  }
  const used = new Set<number>();
  const items = toBulletItems(body);
  topics.slice(0, -1).forEach((t) => items.forEach((it, i) => { if (!used.has(i) && t.keys.test(it)) { used.add(i); out[t.heading] += `${out[t.heading] ? "\n" : ""}• ${it}`; } }));
  const last = topics[topics.length - 1].heading;
  items.forEach((it, i) => { if (!used.has(i)) out[last] += `${out[last] ? "\n" : ""}• ${it}`; });
  return out;
}

export default function PmMarketHealth() {
  const { clientId = "jfr" } = useParams();
  const nav = useNavigate();
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const progress = usePmProgress(clientId);
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const [step, setStep] = useState(2);
  const [vals, setVals] = useState<Record<number, Record<string, string>>>({});
  const [savedAt, setSavedAt] = useState<string | undefined>();
  useEffect(() => {
    if (!pack || !alloc) return;
    const d = loadPackDrafts(clientId);
    setVals(Object.fromEntries([2, 3].map((n) => [n, seed(n, d[n] ?? (clientId === "jfr" ? pack.find((s) => s.n === n)?.body : "") ?? "")])));
  }, [pack, clientId]);
  if (!pack || !alloc) return <Loading />;
  const topics = TOPICS[step];
  const cur = vals[step] ?? {};
  const all = topics.map((t) => cur[t.heading] ?? "").join("\n");
  const { tags } = splitCitations(all);
  const save = (v: typeof vals) => {
    [2, 3].forEach((n) => savePackDraft(clientId, n, composeBlocks(TOPICS[n].map((t) => [t.heading, v[n]?.[t.heading] ?? ""])), "pm"));
    setSavedAt(new Date().toISOString());
  };
  return (
    <div>
      <PmStepper clientId={clientId} current={1} />
      <BackLink to={`/pm/cases/${clientId}/products`}>Back</BackLink>
      <PageHeader eyebrow="Quarterly review" title="Market view and portfolio health" actions={<GateChip id="G2" state="pending" />} />
      <div className="mb-10 inline-flex border border-hairline" role="tablist">
        {[2, 3].map((n) => (
          <button key={n} role="tab" aria-selected={step === n} onClick={() => setStep(n)}
            className={`min-h-10 px-6 text-[15px] ${step === n ? "bg-surface-300 font-normal text-ink" : "font-light text-ink-muted hover:bg-surface-200"}`}>
            {n === 2 ? "1" : "2"}. Section {n}: {TITLES[n]}
          </button>
        ))}
      </div>
      <Section title={`Section ${step}. ${pack.find((s) => s.n === step)?.title ?? TITLES[step]}`}>
        {step === 3 && (
          <div className="mb-12 grid gap-8 md:grid-cols-2">
            <div><h3 className="mb-4 text-base font-light text-ink">Strategic asset allocation</h3>
              <TaaPie title="SAA" labels={alloc.map((a) => a.assetClass)} values={alloc.map((a) => a.saa)} /></div>
            <div><h3 className="mb-4 text-base font-light text-ink">Tactical asset allocation</h3>
              <TaaPie title="TAA" labels={alloc.map((a) => a.assetClass)} values={alloc.map((a, i) => progress.taa?.[i] ?? a.newTaa)} /></div>
          </div>
        )}
        <div className="grid grid-cols-1 gap-x-10 gap-y-12 md:grid-cols-2">
          {topics.map((t, i) => (
            <div key={t.heading} className={`min-w-0 ${topics.length % 2 === 1 && i === topics.length - 1 ? "md:col-span-2" : ""}`}>
              <label htmlFor={`f-${step}-${t.heading}`} className="block text-base font-normal text-ink">{t.heading}</label>
              <p className="mb-3 mt-1 text-sm font-light text-ink-muted">{t.help}</p>
              <BulletTextarea id={`f-${step}-${t.heading}`} rows={5} value={cur[t.heading] ?? ""}
                onChange={(v) => { const next = { ...vals, [step]: { ...cur, [t.heading]: v } }; setVals(next); save(next); }} />
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-ink-muted">Sources: {tags.map((t) => <CitationTag key={t} tag={t} />)}</p>
      </Section>
      <div className="mb-12 flex flex-wrap items-center gap-4">
        <AutoSaveStatus savedAt={savedAt} />
        {step === 2 && <Button variant="secondary" onClick={() => setStep(3)}>Next: portfolio health</Button>}
      </div>
      <NextAction title="Set the tactical allocation" action={<Button variant="primary" onClick={() => nav(`/pm/cases/${clientId}/taa`)}>Continue to TAA</Button>} />
    </div>
  );
}
