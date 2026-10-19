import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { BulletList, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, sgdFull, useAsync } from "../../components/ui";
import { Bar, BackLink, Msg, NumInput } from "./icHelpers";

export const IC_STEPS = [{ label: "3L buckets", hint: "IPS part 2" }, { label: "SAA", hint: "IPS part 4" }, { label: "Send back to RM", hint: "Return to RM" }];

export default function ThreeLBuilder() {
  const { clientId = "jfr" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const buckets = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const ips = useAsync(() => arcApi.getIps(clientId), [clientId]);
  const [amounts, setAmounts] = useState<number[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (buckets) setAmounts(buckets.map((b) => b.amountSgd)); }, [buckets]);
  if (!client || !buckets || !ips) return <Loading />;

  const total = amounts.reduce((a, b) => a + b, 0);
  const diff = client.aumSgd - total;
  const ok = diff === 0;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Build the 3L buckets" subtitle="Split the portfolio into Liquidity, Longevity and Legacy." actions={<GateChip id="G2" state="not_started" />} />
      <Stepper steps={IC_STEPS} current={0} />
      <BackLink to="/ic/inbox">Back to inbox</BackLink>

      <Card className="mb-12">
        <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-left">
          <span><span className="block text-lg font-semibold text-ink">RM's IPS (read-only)</span><span className="text-sm text-ink-500">Open to read what the RM captured</span></span>
          <ChevronDown className={`transition ${open ? "rotate-180" : ""}`} />
        </button>
        {open && (
          <div className="mt-6 flex flex-col gap-5 border-t border-ink-200 pt-6">
            {ips.filter((p) => p.owner === "rm").map((p) => (
              <div key={p.part}><p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-muted">Part {p.part} · {p.title}</p><BulletList text={p.body} className="mt-2 text-ink-700" /></div>
            ))}
          </div>
        )}
      </Card>

      <Section title="Three buckets">
        <div className="flex flex-col gap-8">
          {buckets.map((b, i) => (
            <Card key={b.id}>
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="max-w-md">
                  <h3 className="text-xl">{b.name}</h3>
                  <p className="text-sm text-ink-500">{b.horizon}</p>
                  <p className="mt-2 text-sm text-ink-700">{b.purpose}</p>
                </div>
                <NumInput value={amounts[i] ?? 0} width="w-40" suffix="S$" onChange={(n) => setAmounts(amounts.map((a, j) => (j === i ? n : a)))} />
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

      <NextAction title="Continue to SAA" action={<Button to={`/ic/requests/${clientId}/saa`} disabled={!ok}>Continue to SAA</Button>} />
    </div>
  );
}
