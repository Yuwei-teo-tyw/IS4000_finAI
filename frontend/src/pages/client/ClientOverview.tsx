import { useState } from "react";
import { Card, Loading, Section, Stat, sgd, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { useClient } from "../../components/client/useClient";
import { AllocationBands, type AllocMode } from "../../components/client/AllocationBands";
import { AllocationDonut } from "../../components/client/AllocationDonut";
import { GoalProjection } from "../../components/client/GoalProjection";
import HoldingsExplorer from "../../components/client/HoldingsExplorer";

export default function ClientOverview() {
  const { clientId, client } = useClient();
  const buckets = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const rows = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const groups = useAsync(() => arcApi.getAllocationGroups(clientId), [clientId]);
  const goal = useAsync(() => arcApi.getGoalProjection(clientId), [clientId]);
  const [mode, setMode] = useState<AllocMode>("saa");
  if (!client || !buckets || !rows || !groups || !goal) return <Loading />;

  return (
    <div className="flex flex-col gap-4">
      <div className="-mb-6">
      <Section title="Summary" hint="AUM comes from the client database for book clients; Sharpe ratio and diversification are mock data." mock>
        <div className="grid gap-8 md:grid-cols-3">
          <Stat label="AUM" value={sgd(client.aumSgd)} />
          <Stat label="Sharpe ratio" value={client.sharpe ? client.sharpe.toFixed(2) : "n/a"} />
          <Stat label="Diversification" value={client.diversificationScore ? `${client.diversificationScore}/100` : "n/a"} />
        </div>
      </Section>
      </div>

      <Section title="Goal projection" mock>
        <Card className="!p-8"><GoalProjection data={goal} /></Card>
      </Section>

      <Section title="3L and allocation" mock>
        <Card className="mb-8 !p-8">
          <div className="grid gap-10 lg:grid-cols-2">
            <div className="flex flex-col gap-7">
              <h3 className="text-xl">3L buckets</h3>
              {buckets.map((b) => (
                <div key={b.id}>
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-base text-ink">{b.name} <span className="text-xs text-ink-muted">{b.horizon}</span></span>
                    <span className="text-sm text-ink">{sgd(b.amountSgd)} · {b.pct}%</span>
                  </div>
                  <div className="mt-2 h-2 bg-scale-track"><div className="h-2 bg-scale-fill" style={{ width: `${b.pct}%` }} /></div>
                  <p className="mt-2 text-sm text-ink-muted">{b.purpose}</p>
                </div>
              ))}
            </div>
            <div>
              <h3 className="mb-6 text-xl">Current allocation</h3>
              <AllocationDonut slices={groups} />
            </div>
          </div>
        </Card>
        <Card className="!p-8">
          <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
            <h3 className="text-xl">SAA / Current / TAA with bands</h3>
            <div className="inline-flex rounded-sm border border-ink p-1">
              {(["saa", "taa"] as const).map((m) => (
                <button key={m} onClick={() => setMode(m)}
                  className={`rounded-sm px-5 py-1.5 text-sm ${mode === m ? "bg-surface-inverse text-ink-inverse" : "text-ink"}`}>{m.toUpperCase()}</button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-ink-muted">
                <tr>{["Asset class", "SAA", "Current", "TAA (old)", "Band", "Status"].map((h) => <th key={h} className="pb-4 pr-6 text-xs font-normal">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const lo = r.saa - r.band, hi = r.saa + r.band, out = r.current < lo || r.current > hi;
                  return (
                    <tr key={r.assetClass} className="border-t border-hairline">
                      <td className="py-4 pr-6 text-ink">{r.assetClass}</td>
                      <td className="pr-6">{r.saa}%</td>
                      <td className="pr-6">{r.current}%</td>
                      <td className="pr-6">{r.oldTaa}%</td>
                      <td className="pr-6 text-ink-muted">{Math.max(0, lo)}–{hi}%</td>
                      <td className={out ? "text-negative" : "text-positive"}>{out ? "Outside band" : "Within band"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-10"><AllocationBands rows={rows} mode={mode} /></div>
        </Card>
      </Section>

      <Section title="Holdings" mock>
        <HoldingsExplorer clientId={clientId} />
      </Section>
    </div>
  );
}
