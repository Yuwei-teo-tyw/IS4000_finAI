import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Check, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, useAsync } from "../../components/ui";
import { SectionBody, packToSections, fmtDate } from "./rmShared";
import { SaaDonut } from "../../components/documents/ips/charts";
import { PackSignatures } from "../../components/documents/ips/PackSignatures";
import { loadPackDrafts, loadSignatures, saveSignature, savePackDraft, subscribePackDrafts, subscribeSignatures, type PackDrafts, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { ExportActions } from "../../components/export/ExportActions";

export default function PackReview({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [active, setActive] = useState(1);
  const [drafts, setDrafts] = useState<PackDrafts>(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState<Sigs>(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const [editing, setEditing] = useState(false);
  const [approved, setApproved] = useState(false);
  if (!pack) return <Loading />;
  const allSigned = ["ps", "ic", "rm"].every((r) => sigs[r]);
  const touched = [...Object.keys(drafts).map(Number).filter((n) => n !== 7), ...(allSigned ? [7] : [])];
  const saaVisual = alloc ? (
    <div>
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Strategic asset allocation</p>
      <SaaDonut rows={alloc} />
    </div>
  ) : null;
  const pageExtras: Record<number, React.ReactNode> = {
    1: saaVisual,
    7: <PackSignatures sigs={sigs} onUpload={(role, sig) => saveSignature(clientId, role, sig)} onRemove={(role) => saveSignature(clientId, role, null)} />,
  };
  const docExtras: Record<number, React.ReactNode> = { 1: saaVisual, 7: <PackSignatures sigs={sigs} /> };
  const sections = packToSections(pack, drafts, touched, docExtras);
  const steps = [
    { label: "RM Updates", owner: "rm" },
    { label: "Product Specialist Recommendations", owner: "ps" },
    { label: "IC Portfolio Allocation", owner: "ic" },
  ].map((st) => {
    const mine = sections.filter((x) => x.owner === st.owner);
    return { ...st, done: mine.filter((x) => x.complete).length, total: mine.length };
  });
  const activeStep = steps.findIndex((st) => st.done < st.total);
  const s = pack.find((x) => x.n === active)!;
  const body = drafts[s.n] ?? s.body;
  const canEdit = s.owner === "rm" && s.n !== 7 && !approved;
  const rmOwned = s.owner === "rm";
  const flagged = s.status === "flagged";

  return (
    <div>
      {embedded ? (
        <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h2 className="text-3xl">Review pack</h2>
            <p className="mt-2 text-base text-ink-500">Read each of the 8 sections. You can edit the sections you own (1, 7 and 8), or ask Geneva to draft them; the rest belong to IC and PS.</p>
          </div>
          <GateChip id="G4" state={approved ? "approved" : "pending"} />
        </div>
      ) : (
        <PageHeader eyebrow="Gate G4" title="Review the pack" subtitle="Read each of the 8 sections. You can edit the sections you own (1, 7 and 8), or ask Geneva to draft them; the rest belong to IC and PS."
          actions={<GateChip id="G4" state={approved ? "approved" : "pending"} />} />
      )}
      <ol className="mb-12 grid gap-3 sm:grid-cols-3" aria-label="Review pack progress">
        {steps.map((st, i) => {
          const complete = st.done === st.total;
          const current = i === activeStep;
          return (
            <li key={st.label} className="flex flex-col gap-3">
              <span className="relative h-px overflow-hidden bg-hairline-strong">
                <span className={`absolute inset-y-0 left-0 transition-all duration-700 ${current ? "h-[3px] bg-brand" : "h-[3px] bg-scale-fill"}`} style={{ width: `${st.total ? (st.done / st.total) * 100 : 0}%` }} />
              </span>
              <span className="flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-ink-muted">
                {complete && <Check size={14} />}Step {i + 1}
              </span>
              <span className={`text-[18px] font-light leading-6 ${current ? "text-ink" : "text-ink-muted"}`}>{st.label}</span>
              <span className="text-[13px] text-ink-muted">{st.done} of {st.total} sections complete</span>
            </li>
          );
        })}
      </ol>
      <NextAction title={approved ? "Pack approved" : "Approve the final pack"} body={approved ? "G4 is approved. You can export the PDF." : "Approving G4 releases the PDF. The agent never approves for you."}
        action={approved ? undefined : <Button variant="gold" onClick={() => setApproved(true)}>Approve G4</Button>} />


      <div className="grid gap-8 md:grid-cols-[300px_1fr] md:items-start">
        <Card className="!p-5">
          <h2 className="text-base">Sections</h2>
          <p className="mt-1 text-xs text-ink-muted">{sections.filter((x) => x.complete).length} of {sections.length} complete</p>
          <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><span className="inline-block h-3 w-5 border border-brand" />Sections you fill in</p>
          <nav className="mt-4 flex flex-col gap-2">
            {pack.map((x) => {
              const done = sections.find((y) => y.n === x.n)?.complete;
              return (
                <button key={x.n} onClick={() => { setActive(x.n); setEditing(false); }}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-sm border px-4 py-3.5 text-left text-sm transition-colors duration-300 ${active === x.n ? "bg-surface-inverse text-ink-inverse" : "bg-surface-100 text-ink-700 hover:bg-surface-300"} ${x.owner === "rm" ? "border-brand" : active === x.n ? "border-transparent" : "border-hairline"}`}>
                  <span className="min-w-0">
                    {x.n}. {x.title}
                    {x.status === "flagged" && <AlertTriangle size={14} className="ml-2 inline text-ink-muted" />}
                  </span>
                  {done ? <Check size={16} className={`shrink-0 ${active === x.n ? "text-ink-inverse" : "text-positive"}`} aria-label="Done" /> : <X size={16} className={`shrink-0 ${active === x.n ? "text-ink-inverse" : "text-negative"}`} aria-label="Not done" />}
                </button>
              );
            })}
          </nav>
        </Card>

        <Card className={`min-h-96 !p-10 ${rmOwned ? "!border-brand" : ""}`}>
          <div key={active} className="animate-geneva-in">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[28px] font-light tracking-tight">{s.n}. {s.title}</h2>
              {rmOwned && <p className="mt-1 text-xs uppercase tracking-[0.14em] text-brand">You fill in this section</p>}
            </div>
            <div className="flex gap-2">
              {s.gate && <GateChip id={s.gate} state={s.status === "approved" ? "approved" : s.status === "ready" ? "pending" : "not_started"} />}
              {s.owner === "ic" && <Badge tone="green">IC reviewed thoroughly</Badge>}
              {drafts[s.n] !== undefined && <Badge tone="gold">Updated by you</Badge>}
            </div>
          </div>
          {flagged && (
            <div className="mb-6 flex items-start gap-3 rounded-md bg-surface-300 p-5 text-sm text-ink">
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />Flagged line: please read this section closely before approving.
            </div>
          )}
          {editing && canEdit ? (
            <textarea value={body} onChange={(e) => savePackDraft(clientId, s.n, e.target.value)} rows={10}
              className="w-full rounded-md border border-ink-200 p-5 text-base leading-relaxed outline-none focus:border-ink" />
          ) : (
            <div className="text-[17px] leading-8 text-ink-700"><SectionBody n={s.n} text={body} extra={pageExtras[s.n]} /></div>
          )}
          {canEdit && (
            <div className="mt-6"><Button variant="ghost" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit section"}</Button></div>
          )}
          </div>
        </Card>
      </div>

      <div className="mt-10 flex flex-wrap justify-end">
        <ExportActions docTitle="Quarterly Review Pack" clientName={client?.name ?? clientId} version={approved ? "Approved (G4)" : "Awaiting G4"} date={fmtDate(new Date().toISOString())}
          sections={sections} exportBlocked={!approved} blockedReason="Final export unlocks once G4 is approved." />
      </div>
    </div>
  );
}
