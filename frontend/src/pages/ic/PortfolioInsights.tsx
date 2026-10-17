import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, CitationTag, GateChip, Loading, NextAction, PageHeader, Section, Stepper, Table, useAsync } from "../../components/ui";

export const CASE_STEPS = [{ label: "Review products" }, { label: "Insights" }, { label: "TAA" }, { label: "Pack", hint: "G2" }];

export default function PortfolioInsights() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const products = useAsync(() => arcApi.getProducts(clientId), [clientId]);
  const clusters = useAsync(() => arcApi.getHoldingClusters(clientId), [clientId]);
  const [step, setStep] = useState<0 | 1>(0);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  if (!client || !products || !clusters) return <Loading />;
  const n = products.filter((p) => picked[p.id] ?? true).length;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Quarterly review`} title="Portfolio insights" subtitle="Read what PS approved, then see how the portfolio stands today." actions={<GateChip id="G3" state="approved" />} />
      <Stepper steps={CASE_STEPS} current={step} />

      {step === 0 ? (
        <>
          <Section title="PS-approved products" hint="Read-only. Tick the ones to factor into the TAA.">
            <Table head={["Factor in", "Product", "Class", "Fit", "Sources"]} rows={products.map((p) => [
              <input key="c" type="checkbox" className="h-5 w-5" checked={picked[p.id] ?? true} onChange={(e) => setPicked({ ...picked, [p.id]: e.target.checked })} />,
              <div key="n"><p className="font-semibold text-ink">{p.name}</p><p className="mt-1 text-xs text-ink-500">Risk {p.riskRating} of 5</p></div>,
              p.assetClass, p.suitability, <span key="t">{p.tags.map((t) => <CitationTag key={t} tag={t} />)}</span>,
            ])} />
          </Section>
          <NextAction title="See portfolio insights" body={`${n} of ${products.length} products will be factored in.`} action={<Button onClick={() => setStep(1)}>Continue to insights</Button>} />
        </>
      ) : (
        <>
          <Section title="Strengths and weaknesses">
            <div className="grid gap-8 md:grid-cols-2">
              <Card accent><h3 className="text-xl">Strengths</h3><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-ink-700"><li>Sharpe ratio {client.sharpe}, steady for a Balanced profile</li><li>Diversification score {client.diversificationScore} of 100</li></ul></Card>
              <Card accent><h3 className="text-xl">Weaknesses</h3><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-ink-700">{clusters.map((c) => <li key={c.id}>{c.label} ({c.combinedPct}% of portfolio)</li>)}</ul></Card>
            </div>
          </Section>
          <Section title="Holdings that move together" hint="Plain words, no heatmap here.">
            <div className="flex flex-col gap-8">
              {clusters.map((c) => (
                <Card key={c.id}><div className="flex items-center justify-between"><h3 className="text-lg">{c.label}</h3><Badge tone="amber">{c.combinedPct}%</Badge></div><p className="mt-2 text-sm text-ink-700">{c.note}</p><p className="mt-2 text-xs text-ink-500">{c.holdings.join(" · ")}</p></Card>
              ))}
            </div>
            <p className="mt-6 text-sm"><Link className="font-semibold text-ink underline underline-offset-4" to={`/ic/clients/${clientId}/documents`}>View client's documents (dashboard and heatmap)</Link></p>
          </Section>
          <NextAction title="Propose the TAA" body="Compare old and new tactical weights next." action={<Button variant="gold" to={`/ic/cases/${clientId}/taa`}>Go to TAA</Button>} />
          <button type="button" className="text-sm font-semibold text-ink underline underline-offset-4" onClick={() => setStep(0)}>Back to products</button>
        </>
      )}
    </div>
  );
}
