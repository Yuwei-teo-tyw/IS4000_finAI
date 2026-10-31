import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { arcApi, type PmIps, type PmIpsBucketId } from "../../services/arcApi";
import { returnPmIpsToRm } from "../../services/ipsHandover";
import { Button, Card, GateChip, Loading, NextAction, PageHeader, Section, sgd, useAsyncResult } from "../../components/ui";
import { formatSentAt } from "../rm/ipsSendUtil";
import { Bar, BackLink, Msg, NumInput } from "./pmHelpers";

const BUCKETS: { id: PmIpsBucketId; label: string }[] = [{ id: "liquidity", label: "Liquidity" }, { id: "longevity", label: "Longevity" }, { id: "legacy", label: "Legacy" }];
const SAA: ("longevity" | "legacy")[] = ["longevity", "legacy"];
const mix = (w: Record<string, number> | null) => Object.entries(w ?? {}).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${+v.toFixed(1)}%`).join(" · ");

/** PM step for a DB-backed client: starts from the 3L and strategies the RM generated (GET /pm-ips), edits persist (PUT), sign-off calls /return. Liquidity never has an SAA. */
export default function PmIpsHandover({ clientId }: { clientId: string }) {
  const navigate = useNavigate();
  const [reload, setReload] = useState(0);
  const { data: ips, error } = useAsyncResult(() => arcApi.getPmIps(clientId), [clientId, reload]);
  const { data: strategies } = useAsyncResult(() => arcApi.getStrategies(), []);
  const [pct, setPct] = useState<Record<PmIpsBucketId, number>>({ liquidity: 0, longevity: 0, legacy: 0 });
  const [strat, setStrat] = useState<Record<"longevity" | "legacy", string>>({ longevity: "", legacy: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const fill = (p: PmIps) => {
    setPct({ liquidity: p.threeL.liquidity.pct ?? 0, longevity: p.threeL.longevity.pct ?? 0, legacy: p.threeL.legacy.pct ?? 0 });
    setStrat({ longevity: p.saa.longevity.strategy ?? "", legacy: p.saa.legacy.strategy ?? "" });
  };
  useEffect(() => { if (ips) fill(ips); }, [ips]);
  if (error) return <Msg ok={false}>{error.message}</Msg>;
  if (!ips) return <Loading />;

  const total = pct.liquidity + pct.longevity + pct.legacy;
  const ok = Math.abs(total - 100) < 0.01;
  const dirty = BUCKETS.some((b) => pct[b.id] !== (ips.threeL[b.id].pct ?? 0)) || SAA.some((b) => strat[b] !== (ips.saa[b].strategy ?? ""));
  const run = async (fn: () => Promise<void>) => { setBusy(true); setMsg(null); try { await fn(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Something went wrong." }); } finally { setBusy(false); } };
  const save = async () => {
    const next = await arcApi.savePmIps(clientId, {
      threeL: Object.fromEntries(BUCKETS.map((b) => [b.id, { pct: pct[b.id] }])),
      saa: Object.fromEntries(SAA.filter((b) => strat[b]).map((b) => [b, { strategy: strat[b] }])),
    });
    fill(next); setReload((n) => n + 1);
  };
  const saveClick = () => run(async () => { await save(); setMsg({ ok: true, text: "Saved." }); });
  const signOff = () => run(async () => { if (dirty) await save(); await returnPmIpsToRm(clientId); navigate("/pm/inbox"); });

  return (
    <div>
      <PageHeader eyebrow={`${ips.clientName} · Request`} title="Review the 3L and strategies"
        subtitle={`Starts from what the RM generated in IPS v${ips.version}${ips.sentAt ? ` (sent ${formatSentAt(ips.sentAt)})` : ""}. Edit, then sign off.`}
        actions={<GateChip id="G2" state={ips.returned ? "pending" : "not_started"} />} />

      <Section title="Three buckets" hint={`Percentages must add up to 100% of ${sgd(ips.total)}.`}>
        <div className="flex flex-col gap-8">
          {BUCKETS.map((b) => (
            <Card key={b.id}>
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="max-w-md">
                  <h3 className="text-xl">{b.label}</h3>
                  {ips.threeL[b.id].reason && <p className="mt-2 text-sm text-ink-700">{ips.threeL[b.id].reason}</p>}
                </div>
                <NumInput value={pct[b.id]} width="w-28" suffix="%" onChange={(n) => !ips.returned && setPct({ ...pct, [b.id]: n })} />
              </div>
              <div className="mt-5 flex items-center gap-4">
                <Bar pct={pct[b.id]} tone="gold" />
                <span className="w-32 text-right text-sm font-semibold">{sgd(Math.round((ips.total * pct[b.id]) / 100))}</span>
              </div>
            </Card>
          ))}
        </div>
        <div className="mt-8"><Msg ok={ok}>{ok ? "Total is 100%." : `Total is ${+total.toFixed(2)}%, not 100%.`}</Msg></div>
      </Section>

      <Section title="Strategies" hint="Longevity and Legacy each follow one strategy. Liquidity is held as a reserve.">
        <div className="flex flex-col gap-8">
          {SAA.map((b) => (
            <Card key={b}>
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="max-w-md">
                  <h3 className="text-xl">{b === "longevity" ? "Longevity" : "Legacy"}</h3>
                  {ips.saa[b].reason && <p className="mt-2 text-sm text-ink-700">{ips.saa[b].reason}</p>}
                </div>
                <select value={strat[b]} disabled={ips.returned} onChange={(e) => setStrat({ ...strat, [b]: e.target.value })}
                  className="min-w-56 rounded-md border border-ink-200 bg-surface-100 px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none">
                  {!strat[b] && <option value="">Choose a strategy</option>}
                  {(strategies?.strategies ?? []).map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
                </select>
              </div>
              <p className="mt-4 text-sm text-ink-500">
                {strat[b] === ips.saa[b].strategy ? mix(ips.saa[b].weights) : mix(strategies?.strategies.find((s) => s.code === strat[b])?.allocation ?? null)}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      {msg && <div className="mb-8"><Msg ok={msg.ok}>{msg.text}</Msg></div>}
      {ips.returned ? <Msg ok>Signed off and returned to the RM. Awaiting RM approval.</Msg> : (
        <NextAction title="Sign off and return" body="Saves your edits and returns the IPS to the RM for approval. Nothing is traded."
          action={<div className="flex gap-3"><Button variant="secondary" disabled={busy || !dirty} onClick={saveClick}>Save</Button><Button variant="gold" disabled={busy || !ok || SAA.some((b) => !strat[b])} onClick={signOff}>Sign off and return</Button></div>} />
      )}
      <BackLink to="/pm/inbox">Back to inbox</BackLink>
    </div>
  );
}
