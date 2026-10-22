import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, sgd, sgdFull, useAsync } from "../../components/ui";
import { AutoSaveStatus } from "../../components/pm/SaveProgressButton";
import { savePmProgress, usePmProgress, useIpsReturned } from "../../services/workflowStore";
import { Bar, BackLink, Msg, NumInput } from "./pmHelpers";
import { PM_STEPS } from "./pmSteps";


export default function ThreeLBuilder() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const buckets = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const ips = useAsync(() => arcApi.getIps(clientId), [clientId]);
  const goals = useAsync(() => arcApi.getGoalProjection(clientId), [clientId]);
  const progress = usePmProgress(clientId);
  const returned = useIpsReturned(clientId);
  const [amounts, setAmounts] = useState<number[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  useEffect(() => { if (buckets) setAmounts(progress.buckets && progress.buckets.length === buckets.length ? progress.buckets : buckets.map((b) => b.amountSgd)); }, [buckets]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!client || !buckets || !ips) return <Loading />;

  const total = amounts.reduce((a, b) => a + b, 0);
  const liquidityIdx = buckets.findIndex((b) => b.id === "liquidity");
  const nearGoals = (goals?.events ?? []).filter((e) => e.year - new Date().getFullYear() <= 3 && e.year >= new Date().getFullYear());
  const diff = client.aumSgd - total;
  const ok = diff === 0;
  // Save the PM's amounts so the SAA step (and the Portfolio Agent) use them.
  const continueToSaa = async () => {
    await arcApi.save3L(clientId, buckets.map((b, i) => ({ ...b, amountSgd: amounts[i] ?? 0, pct: client.aumSgd ? Math.round(((amounts[i] ?? 0) / client.aumSgd) * 100) : 0 })));
    navigate(`/pm/requests/${clientId}/saa`);
  };

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Build the 3L buckets" subtitle="Split the portfolio into Liquidity, Longevity and Legacy." actions={<GateChip id="G2" state={returned ? "pending" : "not_started"} />} />
      <Stepper steps={PM_STEPS} current={0} />

      <Card className="mb-12">
        <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-left">
          <span><span className="block text-lg font-semibold text-ink">RM's IPS (read-only)</span><span className="text-sm text-ink-500">Open to read what the RM captured</span></span>
          <ChevronDown className={`transition ${open ? "rotate-180" : ""}`} />
        </button>
        {open && (
          <div className="mt-6 flex flex-col gap-5 border-t border-ink-200 pt-6">
            {ips.filter((p) => p.owner === "rm").map((p) => (
              <div key={p.part}><p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-muted">Part {p.part} · {p.title}</p><p className="mt-1 text-sm text-ink-700">{p.body}</p></div>
            ))}
          </div>
        )}
      </Card>

      <Section title="Three buckets" hint={`Amounts must add up to the portfolio of ${sgd(client.aumSgd)}.`}>
        <div className="flex flex-col gap-8">
          {buckets.map((b, i) => (
            <Card key={b.id}>
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="max-w-md">
                  <h3 className="text-xl">{b.name}</h3>
                  <p className="text-sm text-ink-500">{b.horizon}</p>
                  <p className="mt-2 text-sm text-ink-700">{b.purpose}</p>
                </div>
                <NumInput value={amounts[i] ?? 0} width="w-40" suffix="S$" onChange={(n) => { const next = amounts.map((a, j) => (j === i ? n : a)); setAmounts(next); savePmProgress(clientId, { buckets: next }); }} />
              </div>
              <div className="mt-5 flex items-center gap-4">
                <Bar pct={client.aumSgd ? ((amounts[i] ?? 0) / client.aumSgd) * 100 : 0} tone="gold" />
                <span className="w-14 text-right text-sm font-semibold">{client.aumSgd ? Math.round(((amounts[i] ?? 0) / client.aumSgd) * 100) : 0}%</span>
              </div>
            </Card>
          ))}
        </div>
        <div className="mt-8">
          <Msg ok={ok}>{ok ? `Total is ${sgdFull(total)}. Matches the portfolio.` : `Total is ${sgdFull(total)}. ${diff > 0 ? `${sgdFull(diff)} still to place.` : `${sgdFull(-diff)} over the portfolio.`}`}</Msg>
        </div>
      </Section>

      <div className="mb-6 flex justify-end"><AutoSaveStatus savedAt={progress.savedAt} /></div>
      {nearGoals.length > 0 && (amounts[liquidityIdx] ?? 0) === 0 && (
        <div className="mb-8"><Msg ok={false}>{nearGoals.map((g) => `${g.label} (${g.year})`).join(" and ")} {nearGoals.length === 1 ? "falls" : "fall"} due within 3 years, but the Liquidity bucket is empty. Money needed soon should sit in Liquidity.</Msg></div>
      )}
      <NextAction title="Continue to SAA" body="Once the buckets add up, the Portfolio Agent builds a separate SAA for each bucket, for its own purpose and horizon. Changing an amount later means re-running that bucket only." action={<Button onClick={continueToSaa} disabled={!ok}>Continue to SAA</Button>} />
      <BackLink to="/pm/inbox">Back to inbox</BackLink>
    </div>
  );
}
