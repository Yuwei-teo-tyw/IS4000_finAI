import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { saveIcProgress, useIcProgress } from "../../services/workflowStore";
import { IcStepper } from "../../components/ic/IcStepper";
import { AutoSaveStatus } from "../../components/ic/SaveProgressButton";
import { TaaPie } from "../../components/ic/TaaPie";
import { Button, DirectionArrow, GateChip, Loading, NextAction, PageHeader, Table, useAsync } from "../../components/ui";
import { syncPackFromIc } from "../../components/ic/packSync";
import { BackLink, NumInput, sum } from "./icHelpers";

const r1 = (n: number) => Math.round(n * 10) / 10;
const GREEN = "text-up", RED = "text-down";
function Status({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-2 text-[13px] ${ok ? GREEN : RED}`} role="status">{ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}{children}</span>;
}
function Head({ title, status, h = "text-[28px] leading-[34px]" }: { title: React.ReactNode; status?: React.ReactNode; h?: string }) {
  return <div className="mb-8 flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2"><h2 className={h}>{title}</h2>{status}</div>;
}
function Ytd({ v }: { v: number }) {
  if (v === 0) return <span>0%</span>;
  return <span className={`inline-flex items-center gap-1 ${v > 0 ? GREEN : RED}`}><DirectionArrow d={v} size={12} />{v > 0 ? "+" : ""}{v}%</span>;
}
function Dir({ d }: { d: number }) {
  return <DirectionArrow d={Math.abs(d) < 0.05 ? "flat" : d} />;
}
const sgd = (n: number) => n.toLocaleString("en-SG", { maximumFractionDigits: 0 });

export default function IcHoldings() {
  const { clientId = "jfr" } = useParams();
  const navigate = useNavigate();
  const holdings = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const progress = useIcProgress(clientId);
  const [w, setW] = useState<Record<string, number>>({});

  const base = useMemo(() => {
    const b: Record<string, number> = {};
    (holdings ?? []).forEach((h) => { b[h.id] = progress.holdings?.[h.id] ?? h.weightPct; });
    return b;
  }, [holdings, progress.holdings]);
  useEffect(() => { if (holdings) setW(base); }, [holdings]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!holdings || !alloc) return <Loading />;

  const taa = alloc.map((r, i) => (progress.taa && progress.taa.length === alloc.length ? progress.taa[i] : r.newTaa));
  const target = (cls: string) => taa[alloc.findIndex((r) => r.assetClass === cls)];
  const cur = (id: string) => w[id] ?? base[id] ?? 0;
  const classes = Array.from(new Set([...alloc.map((r) => r.assetClass), ...holdings.map((h) => h.assetClass)]));
  const classSum = (cls: string) => r1(sum(holdings.filter((h) => h.assetClass === cls).map((h) => cur(h.id))));
  const total = r1(sum(holdings.map((h) => cur(h.id))));
  const off = classes.filter((c) => target(c) !== undefined && Math.abs(classSum(c) - target(c)) > 0.05);
  const edit = (id: string, n: number) => { const next = { ...w, [id]: n }; setW(next); saveIcProgress(clientId, { holdings: { ...base, ...next } }); syncPackFromIc(clientId); };
  const save = () => { saveIcProgress(clientId, { holdings: { ...base, ...w } }); syncPackFromIc(clientId); };

  return (
    <div>
      <IcStepper clientId={clientId} current={3} />
      <BackLink to={`/ic/cases/${clientId}/taa`}>Back to TAA</BackLink>
      <PageHeader eyebrow="Quarterly review" title="Review client individual holdings" subtitle="Adjust each holding's weight so classes follow the TAA." actions={<GateChip id="G2" state="pending" />} />
      <section className="mb-20">
        <Head title="TAA and holdings mix" status={off.length > 0 ? <Status ok={false}>Off target: {off.join(", ")}</Status> : <Status ok>All classes on target</Status>} />
        <div className="grid grid-cols-1 gap-12 md:grid-cols-2">
          <TaaPie title="TAA" labels={alloc.map((r) => r.assetClass)} values={taa} />
          <TaaPie title="Individual holdings" labels={holdings.map((h) => h.name)} values={holdings.map((h) => cur(h.id))} />
        </div>
      </section>
      <section className="mb-20">
        <Head title="Holdings by asset class" status={<Status ok={Math.abs(total - 100) <= 0.05}>{Math.abs(total - 100) <= 0.05 ? "Grand total 100%" : `Grand total ${total}%, not 100%`}</Status>} />
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-2 lg:gap-12">
          {classes.map((cls) => {
            const hs = holdings.filter((h) => h.assetClass === cls);
            if (hs.length === 0) return null;
            const t = target(cls), s = classSum(cls);
            const o = r1(sum(hs.map((h) => h.weightPct)));
            const diff = r1(s - t);
            const pts = Math.abs(diff);
            return (
              <div key={cls} className={`min-w-0 border border-hairline bg-surface-100 p-8 ${hs.length > 6 ? "lg:col-span-2" : ""}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
                  <h3 className="text-lg">{cls} <span className="text-ink-muted">· TAA {t ?? "n/a"}% · holdings {s}%</span></h3>
                  {t === undefined ? <span className="text-[13px] text-ink-muted">No TAA target</span> : pts <= 0.05 ? <Status ok>On target</Status> : <Status ok={false}>{pts} {pts === 1 ? "pt" : "pts"} {diff > 0 ? "above" : "below"} {t}% target</Status>}
                </div>
                <p className="mb-6 mt-2 flex items-center gap-1 text-[13px] text-ink-muted">Class total: old {o}% <Dir d={s - o} /> new {s}%</p>
                <div className="overflow-x-auto">
                  <Table head={["Holding", "Value", "YTD", "Old", "New", ""]} rows={hs.map((h) => {
                    const o1 = h.weightPct;
                    return [
                      <span key="h" className="block">{h.name}<span className="block text-[12px] text-ink-muted">{h.ticker ?? "-"}</span></span>,
                      sgd(h.valueSgd),
                      <Ytd key="y" v={h.returnYtdPct} />,
                      `${o1}%`,
                      <NumInput key="n" value={cur(h.id)} suffix="%" width="w-20" onChange={(n) => edit(h.id, n)} />,
                      <Dir key="d" d={cur(h.id) - o1} />,
                    ];
                  })} />
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <div className="mb-14 flex justify-end border-t border-hairline pt-8"><AutoSaveStatus savedAt={progress.savedAt} /></div>
      <NextAction title="Check the Review Pack" action={<Button variant="primary" onClick={() => { save(); navigate(`/ic/cases/${clientId}/pack`); }}>Check Review Pack</Button>} />
    </div>
  );
}
