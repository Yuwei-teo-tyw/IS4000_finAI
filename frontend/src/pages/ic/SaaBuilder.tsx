import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, Table, useAsync } from "../../components/ui";
import { ASSETS, BackLink, Msg, NumInput, growthLimit, growthShare, sum } from "./icHelpers";
import { IC_STEPS } from "./ThreeLBuilder";

const TABS = ["Template", "Edit weights", "Frontier"] as const;

export default function SaaBuilder() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const templates = useAsync(() => arcApi.getSaaTemplates());
  const [tab, setTab] = useState<(typeof TABS)[number]>("Template");
  const [tid, setTid] = useState("C");
  const [vals, setVals] = useState<number[]>([]);
  const [sent, setSent] = useState(false);
  useEffect(() => { if (templates) setVals([...templates.find((t) => t.id === "C")!.split]); }, [templates]);
  if (!client || !templates) return <Loading />;

  const tpl = templates.find((t) => t.id === tid)!;
  const pick = (id: string) => { setTid(id); setVals([...templates.find((t) => t.id === id)!.split]); setSent(false); };
  const total = sum(vals);
  const limit = growthLimit(client.riskCap);
  const growth = growthShare(vals);
  const far = ASSETS.filter((_, i) => Math.abs(vals[i] - tpl.split[i]) > 5);
  const totalOk = total === 100, capOk = growth <= limit, bandOk = far.length === 0;
  const valid = totalOk && capOk && bandOk;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Build the SAA" subtitle="Choose a template, then adjust each class by up to 5 points." actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={IC_STEPS} current={sent ? 2 : 1} />

      <div className="mb-10 flex gap-3">
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)} className={`rounded-full px-5 py-2 text-sm font-semibold ${tab === t ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{t}</button>
        ))}
      </div>

      {tab === "Template" && (
        <Section title="Pick a template" hint="Templates A to F run from cautious to opportunistic.">
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((t) => (
              <button key={t.id} type="button" onClick={() => pick(t.id)} className="text-left">
                <Card className={tid === t.id ? "ring-2 ring-ink" : ""}>
                  <div className="flex items-center justify-between"><h3 className="text-xl">{t.id} · {t.name}</h3>{tid === t.id && <Badge tone="gold">Selected</Badge>}</div>
                  <p className="mt-4 text-sm text-ink-500">Equities {t.split[2]}% · Fixed income {t.split[1]}% · Cash {t.split[0]}%</p>
                </Card>
              </button>
            ))}
          </div>
        </Section>
      )}

      {tab === "Edit weights" && (
        <Section title="Edit the seven classes" hint={`Template ${tpl.id}. Each class within 5 points of it, total 100, growth assets at most ${limit}% (risk limit ${client.riskCap}).`}>
          <Table head={["Asset class", "Template", "Your SAA", "Gap"]} rows={ASSETS.map((a, i) => {
            const gap = vals[i] - tpl.split[i];
            return [a, `${tpl.split[i]}%`, <NumInput key={a} value={vals[i] ?? 0} suffix="%" onChange={(n) => setVals(vals.map((v, j) => (j === i ? n : v)))} />,
              <span key="g" className={Math.abs(gap) > 5 ? "font-semibold text-negative" : "text-ink-500"}>{gap > 0 ? "+" : ""}{gap}</span>];
          })} />
          <div className="mt-8 flex flex-col gap-4">
            <Msg ok={totalOk}>{totalOk ? "Total is 100." : `Total is ${total}. It must be 100.`}</Msg>
            <Msg ok={capOk}>{capOk ? `Growth assets ${growth}%, inside the ${limit}% limit.` : `Growth assets ${growth}% exceed the ${limit}% limit.`}</Msg>
            <Msg ok={bandOk}>{bandOk ? "All classes within 5 points of the template." : `Too far from template: ${far.join(", ")}.`}</Msg>
          </div>
        </Section>
      )}

      {tab === "Frontier" && (
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

      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg> : valid ? (
        <NextAction title="Limit check passed" body="Everything is inside the rules. Send the 3L and SAA back to the RM." action={<Button variant="gold" onClick={() => setSent(true)}>Send back to RM</Button>} />
      ) : (
        <NextAction title="Blocked: fix the checks first" body="Open Edit weights and resolve the red messages. Sending stays off until all three pass." action={<Button disabled>Send back to RM</Button>} />
      )}
      <BackLink to={`/ic/requests/${clientId}/3l`}>Back to 3L</BackLink>
    </div>
  );
}
