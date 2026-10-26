import { useRole } from "../../layouts/AppShell";
import { Card, CitationTag, Loading, Section, Stat, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { useClient } from "../../components/client/useClient";
import { CorrelationHeatmap } from "../../components/client/CorrelationHeatmap";
import { HoldingsTable } from "../../components/client/HoldingsTable";
import { MeetingNotesList } from "../../components/documents/MeetingNotesList";
import { IpsHistory } from "./IpsHistory";


function FullDocuments() {
  const { clientId, client } = useClient();
  const corr = useAsync(() => arcApi.getCorrelation(clientId), [clientId]);
  const clusters = useAsync(() => arcApi.getHoldingClusters(clientId), [clientId]);
  const holdings = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const notes = useAsync(() => arcApi.getMeetingNotes(clientId), [clientId]);
  if (!client || !corr || !clusters || !holdings || !alloc || !notes) return <Loading />;
  const drift = Math.max(...alloc.map((r) => Math.abs(r.current - r.saa)));

  return (
    <div>
      <h2 className="mb-10 text-3xl">IPS</h2>
      <IpsHistory clientId={clientId} clientName={client.name} />

      <div>
        <Section title="Portfolio analytics" hint="Computed by code." mock>
          <div className="grid gap-8 md:grid-cols-3">
            <div><Stat label="Sharpe ratio" value={client.sharpe.toFixed(2)} note="Return per unit of risk" /><p className="mt-3 text-sm text-ink-muted"><CitationTag tag="CALC-sharpe-v1" /></p></div>
            <div><Stat label="Diversification score" value={`${client.diversificationScore}/100`} /><p className="mt-3 text-sm text-ink-muted"><CitationTag tag="CALC-divscore-v1" /></p></div>
            <div><Stat label="Max drift vs SAA" value={`${drift} pts`} note={drift > 5 ? "Outside the 5-point band" : "Within the 5-point band"} /><p className="mt-3 text-sm text-ink-muted"><CitationTag tag="CALC-drift-v1" /></p></div>
          </div>
        </Section>
      </div>

      <div>
        <Section title="Correlation heatmap" mock>
          <Card className="!p-8"><CorrelationHeatmap labels={corr.labels} matrix={corr.matrix} /></Card>
        </Section>
      </div>

      <div>
        <Section title="Holdings that move together" mock>
          <div className="grid gap-8 md:grid-cols-2">
            {clusters.map((c) => (
              <Card key={c.id} className="!p-8">
                <h3 className="text-xl">{c.label}</h3>
                <p className="mt-3 text-sm text-ink-muted">{c.combinedPct}% of the portfolio. {c.note}</p>
                <ul className="mt-5 space-y-2 text-sm text-ink">{c.holdings.map((h) => <li key={h} className="border-t border-hairline pt-2">{h}</li>)}</ul>
              </Card>
            ))}
          </div>
        </Section>
      </div>

      <div>
        <Section title="Holdings" mock><HoldingsTable holdings={holdings} /></Section>
      </div>

      <div>
        <Section title="Meeting notes">
          {notes.length === 0 && <p className="text-sm text-ink-muted">No meeting notes yet.</p>}
          {notes.length > 0 && <MeetingNotesList notes={notes} clientName={client.name} />}
        </Section>
      </div>
    </div>
  );
}

export default function ClientDocuments() {
  const role = useRole();
  const { clientId } = useClient();
  if (role === "rm") {
    return (
      <div>
        <h2 className="mb-10 text-3xl">IPS</h2>
        <IpsHistory clientId={clientId} />
      </div>
    );
  }
  return <FullDocuments />;
}
