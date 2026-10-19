import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Check } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, GateChip, Loading, NextAction, PageHeader, useAsync } from "../../components/ui";
import { packToSections, fmtDate, SignoffBoxes, SourcesBoard, isSources, usePackStatus, isHiddenFor, PendingBox } from "./rmShared";
import { PackSectionPanel } from "./PackSectionPanel";
import { GenevaMark } from "../../components/documents/GenevaMark";
import { PackDocument } from "./PackDocument";
import { syncPackFromIc } from "../../components/ic/packSync";
import { loadPackDrafts, loadSignatures, saveSignature, subscribePackDrafts, subscribeSignatures, type PackDrafts, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { sendReviewRequest, withdrawReviewRequest, useReviewRequest, useAllFinalised, useIcProgress, useIcHandover } from "../../services/workflowStore";
import { useRole } from "../../layouts/AppShell";
import { ExportActions } from "../../components/export/ExportActions";

export default function PackReview({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const role = useRole();
  const isIc = role === "ic";
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [drafts, setDrafts] = useState<PackDrafts>(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState<Sigs>(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const progress = useIcProgress(clientId);
  const holdingsList = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const [approved, setApproved] = useState(false);
  const sent = useReviewRequest(clientId);
  const finalisedByPs = useAllFinalised().some((f) => f.clientId === clientId);
  /** 0 = RM updates, 1 = waiting on Product Specialist, 2 = with IC. */
  const stage = finalisedByPs ? 2 : sent ? 1 : 0;
  const status = usePackStatus(clientId);
  const icHandover = useIcHandover(clientId);
  // Keep sections 4 and 8 in step with the IC's saved values: on mount, on every IC save and when the IC hands over.
  useEffect(() => { if (progress.savedAt || icHandover) syncPackFromIc(clientId); }, [progress.savedAt, icHandover?.sentAt, clientId]);
  const [openMap, setOpenMap] = useState<Record<number, boolean>>({});
  const onboarding = client?.status === "Onboarding Phase";
  if (!pack) return <Loading />;
  const pos = (n: number) => pack.findIndex((x) => x.n === n) + 1;
  const allSigned = ["ps", "ic", "rm"].every((r) => sigs[r]);
  const signoffN = pack.find((x) => x.kind === "signoff")?.n;
  const sourcesN = pack.find(isSources)?.n;
  const touched = [...Object.keys(drafts).map(Number).filter((n) => n !== signoffN), ...(allSigned && signoffN ? [signoffN] : [])];
  const savedTaa = alloc && progress.taa && progress.taa.length === alloc.length ? progress.taa : null;
  const editedHoldings = progress.holdings && Object.keys(progress.holdings).length > 0 ? progress.holdings : null;
  const icUpdated: Record<number, boolean> = { 4: !!savedTaa, 8: !!editedHoldings };
  const pageExtras: Record<number, React.ReactNode> = {
    ...(signoffN ? { [signoffN]: <SignoffBoxes sigs={sigs} me={role} onSign={(r, sig) => saveSignature(clientId, r, sig)} onRemove={(r) => saveSignature(clientId, r, null)} /> } : {}),
    ...(sourcesN ? { [sourcesN]: <SourcesBoard clientId={clientId} me={role} editing={false} hideEditButton /> } : {}),
  };
  const sections = packToSections(clientId, pack, drafts, touched, pageExtras).map((x) => ({ ...x, complete: !!status.complete[x.n], ...(isHiddenFor(x, role, status.complete) && !isSources(x) ? { body: <PendingBox owner={x.owner} /> } : {}) }));
  const steps = [
    { label: "RM Updates", owner: "rm" },
    { label: "Product Specialist Recommendations", owner: "ps" },
    { label: "IC Portfolio Allocation", owner: "ic" },
  ].map((st) => {
    const mine = sections.filter((x) => x.owner === st.owner && x.n !== signoffN);
    const done = mine.filter((x) => x.complete).length;
    const gate = st.owner === "rm" ? sent || finalisedByPs : st.owner === "ps" ? finalisedByPs : !!icHandover;
    const finished = mine.length > 0 && done === mine.length && gate;
    return { ...st, done: finished ? mine.length : done, total: mine.length, finished };
  });
  const firstOpen = steps.findIndex((st) => !st.finished);
  const activeStep = firstOpen === -1 ? -1 : firstOpen;
  const allComplete = status.doneCount === status.total && status.total > 0;
  const ownIds = pack.filter((x) => x.owner === role && x.kind !== "signoff").map((x) => x.n);
  const pending = ownIds.filter((n) => !status.done[n]?.done);
  const sendReady = pending.length === 0;
  const pendingLabel = pending.map(pos);
  const sendReason = `Mark section${pendingLabel.length > 1 ? "s" : ""} ${pendingLabel.length > 1 ? `${pendingLabel.slice(0, -1).join(", ")} and ${pendingLabel[pendingLabel.length - 1]}` : pendingLabel[0]} as done to send.`;
  const extraFor = (n: number) => (n === signoffN || n === sourcesN
    ? (editing: boolean) => (n === signoffN ? pageExtras[n] : <SourcesBoard clientId={clientId} me={role} editing={editing} hideEditButton />)
    : undefined);
  const updatedNote = (n: number) => (icUpdated[n] && progress.savedAt ? `Updated from the IC workspace, saved ${new Date(progress.savedAt).toLocaleString("en-SG", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}.` : undefined);
  const isOpen = (n: number, owner: string) => openMap[n] ?? owner === role;
  const allOpen = pack.every((x) => isOpen(x.n, x.owner));
  const setAll = (v: boolean) => setOpenMap(Object.fromEntries(pack.map((x) => [x.n, v])));
  const quarter = `Q${Math.floor(new Date().getMonth() / 3) + 1} ${new Date().getFullYear()}`;

  const exportActions = (
    <ExportActions docTitle="Quarterly Review Pack" clientName={client?.name ?? clientId} version={approved ? "Approved (G4)" : "Awaiting G4"} date={fmtDate(new Date().toISOString())}
      sections={sections}
      document={<PackDocument clientId={clientId} clientName={client?.name ?? clientId} version={approved ? "Approved (G4)" : "Awaiting G4"} pack={pack} alloc={alloc} holdings={holdingsList} approved={approved} />}
      exportBlocked={!approved} blockedReason="Final export unlocks once G4 is approved." />
  );

  return (
    <div>
      <>
      {embedded ? (
        <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h2 className="text-3xl">Review pack</h2>
            <p className="mt-2 text-base text-ink-500">Edit the sections you own; the rest belong to {isIc ? "RM and PS" : "IC and PS"}.</p>
          </div>
          <GateChip id="G4" state={approved ? "approved" : "pending"} />
        </div>
      ) : (
        <PageHeader eyebrow="Gate G4" title="Review the pack" subtitle={`Edit the sections you own; the rest belong to ${isIc ? "RM and PS" : "IC and PS"}.`}
          actions={<GateChip id="G4" state={approved ? "approved" : "pending"} />} />
      )}
      {!isIc && <ol className="mb-12 grid gap-3 sm:grid-cols-3" aria-label="Review pack progress">
        {steps.map((st, i) => {
          const complete = st.finished;
          const current = i === activeStep;
          return (
            <li key={st.label} className="flex flex-col gap-3">
              <span className="relative h-px overflow-hidden bg-hairline-strong">
                <span className="absolute inset-y-0 left-0 h-[3px] bg-brand transition-all duration-700" style={{ width: `${complete ? 100 : current && st.total ? (st.done / st.total) * 100 : 0}%` }} />
              </span>
              <span className="flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-ink-muted">
                {complete && <Check size={14} />}Step {i + 1}
              </span>
              <span className={`text-[18px] font-light leading-6 ${current ? "text-ink" : "text-ink-muted"}`}>{st.label}</span>
              <span className="text-[13px] text-ink-muted">{complete ? `Done, ${st.total} of ${st.total} sections complete` : current ? `${st.done} of ${st.total} sections complete` : "Waiting"}</span>
            </li>
          );
        })}
      </ol>}
      {!isIc && stage === 0 && (
        <NextAction title="Send to Product Specialist" body={sendReady ? "Send this client to the Product Specialist for product research." : sendReason}
          action={<Button disabled={!sendReady} onClick={() => sendReviewRequest(clientId)}>Send to Product Specialist</Button>} />
      )}
      {!isIc && stage === 1 && (
        <NextAction title="Sent to Product Specialist" body="Waiting for the Product Specialist."
          action={<Button variant="secondary" onClick={() => withdrawReviewRequest(clientId)}>Withdraw request</Button>} />
      )}
      {!isIc && stage === 2 && (allComplete || approved) && (
        <NextAction title={approved ? "Pack approved" : "Approve the final pack"} body={approved ? "G4 is approved. You can export the PDF." : "Approving G4 releases the PDF. The agent never approves."}
          action={approved ? undefined : <Button onClick={() => setApproved(true)}>Approve G4</Button>} />
      )}

      </>

      <article className="w-full min-w-0 border border-hairline bg-surface-100 px-4 py-10 text-ink shadow-card sm:px-8 sm:py-14">
        <header className="mb-14">
          <GenevaMark className="mb-10" />
          <p className="text-[12px] uppercase tracking-[0.14em] text-ink-muted">Quarterly review pack</p>
          <h1 className="mt-3 text-[40px] font-light leading-[48px]">{client?.name ?? clientId}</h1>
          <div className="mt-6 h-px w-full bg-ink" />
          <p className="mt-4 text-sm text-ink-muted">{quarter} · {approved ? "Approved (G4)" : "Awaiting G4"} · {status.doneCount} of {sections.length} sections complete</p>
        </header>
        <div className="mb-8 flex justify-end">
          <button type="button" onClick={() => setAll(!allOpen)} className="cursor-pointer text-[13px] uppercase tracking-[0.12em] text-ink-muted hover:text-ink">{allOpen ? "Collapse all" : "Expand all"}</button>
        </div>
        <div className="space-y-12">
          {pack.map((x, idx) => (
            <div key={x.n}>
              <div className="mb-10 h-px w-full bg-hairline" />
              <PackSectionPanel clientId={clientId} s={x} pos={idx + 1} role={role} onboarding={onboarding} approved={approved} status={status} alloc={alloc}
                open={isOpen(x.n, x.owner)} onToggle={() => setOpenMap((m) => ({ ...m, [x.n]: !isOpen(x.n, x.owner) }))} extra={extraFor(x.n)} updatedNote={updatedNote(x.n)} />
            </div>
          ))}
        </div>
      </article>

      <div className="mt-10 flex flex-wrap justify-end">{exportActions}</div>
    </div>
  );
}
