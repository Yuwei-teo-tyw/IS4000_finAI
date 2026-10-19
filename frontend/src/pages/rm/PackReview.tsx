import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Check, Lock, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, useAsync } from "../../components/ui";
import { ProfileCarousel, SaaPanel, parseSaaText, SectionBlocksView, SectionBody, WordingCompare, packToSections, useSeededBlocks, withText, primaryText, fmtDate, SignoffBoxes, SourcesBoard, isSources, usePackStatus, isHiddenFor, PendingBox } from "./rmShared";
import { hasHeadings, parseBlocks, composeBlocks } from "../../services/packBlocks";
import { PackDocument } from "./PackDocument";
import { syncPackFromIc } from "../../components/ic/packSync";
import { BlockEditor, saveSectionBlocks } from "../../components/documents/pack";
import { loadPackDrafts, loadSignatures, saveSignature, setSectionDone, subscribePackDrafts, subscribeSignatures, type PackDrafts, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { sendReviewRequest, withdrawReviewRequest, useReviewRequest, useAllFinalised, useIcProgress, ipsKey, sendIpsToIc, withdrawIpsToIc, useIpsRequest, useIpsIcHandover, useIpsComplete, setIpsComplete } from "../../services/workflowStore";
import { useRole } from "../../layouts/AppShell";
import { ProfessionaliseButton } from "../../components/geneva/ProfessionaliseButton";
import { getChatContext } from "../../services/chatContextStore";
import { ExportActions } from "../../components/export/ExportActions";

export default function PackReview({ embedded = false, clientId: clientIdProp, workflow = "pack" }: { embedded?: boolean; clientId?: string; workflow?: "pack" | "ips" }) {
  const params = useParams();
  const realId = clientIdProp ?? params.clientId ?? "";
  const ips = workflow === "ips";
  /** Store key: ipsKey(clientId) in IPS mode so drafts, blocks, done flags and history never collide with the review pack. */
  const clientId = ips ? ipsKey(realId) : realId;
  const role = useRole();
  const isIc = role === "ic";
  const pack = useAsync(() => (ips ? arcApi.getIpsSections(realId) : arcApi.getPack(realId)), [realId, ips]);
  const client = useAsync(() => arcApi.getClient(realId), [realId]);
  const alloc = useAsync(() => arcApi.getAllocation(realId), [realId]);
  const [active, setActive] = useState(1);
  const [drafts, setDrafts] = useState<PackDrafts>(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState<Sigs>(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const progress = useIcProgress(realId);
  const holdingsList = useAsync(() => arcApi.getHoldings(realId), [realId]);
  const [editing, setEditing] = useState(false);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [compare, setCompare] = useState<{ n: number; oldText: string; newText: string } | null>(null);
  const [polishErr, setPolishErr] = useState("");
  const sentPack = useReviewRequest(realId);
  const finalisedByPs = useAllFinalised().some((f) => f.clientId === realId);
  const sentIps = !!useIpsRequest(realId);
  const ipsBack = !!useIpsIcHandover(realId);
  const ipsDone = useIpsComplete(realId);
  /** Pack: 0 = RM updates, 1 = waiting on Product Specialist, 2 = with IC. IPS: 0 = RM fills, 1 = with IC, 2 = back with RM. */
  const stage = ips ? (ipsBack ? 2 : sentIps ? 1 : 0) : finalisedByPs ? 2 : sentPack ? 1 : 0;
  const status = usePackStatus(realId, workflow);
  const needSync = !ips && !!progress.savedAt && drafts[4] === undefined;
  useEffect(() => { if (needSync) syncPackFromIc(clientId); }, [needSync, clientId]);
  const sec0 = pack?.find((x) => x.n === active);
  const onboarding = client?.status === "Onboarding Phase";
  const blocks = useSeededBlocks(clientId, active, sec0?.body ?? "", sec0?.chart, ips || (onboarding && sec0?.chart === "saa"));
  if (!pack) return <Loading />;
  const pos = (n: number) => pack.findIndex((x) => x.n === n) + 1;
  const allSigned = ["ps", "ic", "rm"].every((r) => sigs[r]);
  const signoffN = pack.find((x) => x.kind === "signoff")?.n;
  const sourcesN = ips ? undefined : pack.find(isSources)?.n;
  const touched = [...Object.keys(drafts).map(Number).filter((n) => n !== signoffN), ...(allSigned && signoffN ? [signoffN] : [])];
  const savedTaa = alloc && progress.taa && progress.taa.length === alloc.length ? progress.taa : null;
  const editedHoldings = progress.holdings && Object.keys(progress.holdings).length > 0 ? progress.holdings : null;
  const icUpdated: Record<number, boolean> = ips ? {} : { 4: !!savedTaa, 8: !!editedHoldings };
  const pageExtras: Record<number, React.ReactNode> = {
    ...(signoffN ? { [signoffN]: <SignoffBoxes sigs={sigs} me={role} onSign={(r, sig) => saveSignature(clientId, r, sig)} onRemove={(r) => saveSignature(clientId, r, null)} /> } : {}),
    ...(sourcesN ? { [sourcesN]: <SourcesBoard clientId={clientId} me={role} editing={editing} hideEditButton /> } : {}),
  };
  const sections = packToSections(clientId, pack, drafts, touched, pageExtras).map((x) => ({ ...x, complete: !!status.complete[x.n], ...(isHiddenFor(x, role, status.complete) && !isSources(x) ? { body: <PendingBox owner={x.owner} /> } : {}) }));
  const stepDefs = ips
    ? [{ label: "RM fills the IPS", owner: "rm" }, { label: "IC proposes the asset allocation", owner: "ic" }]
    : [{ label: "RM Updates", owner: "rm" }, { label: "Product Specialist Recommendations", owner: "ps" }, { label: "IC Portfolio Allocation", owner: "ic" }];
  const steps = stepDefs.map((st) => {
    const mine = sections.filter((x) => x.owner === st.owner);
    return { ...st, done: mine.filter((x) => x.complete).length, total: mine.length };
  });
  const activeStep = ips && stage === 2 ? 1 : stage;
  const s = pack.find((x) => x.n === active)!;
  const textNow = primaryText(blocks);
  const canEdit = s.owner === role && s.kind !== "signoff" && !isSources(s) && !approved && !(ips && ipsDone);
  const rmOwned = (s.owner === role && s.kind !== "signoff") || s.kind === "signoff";
  const hiddenS = isHiddenFor(s, role, status.complete) && !isSources(s);
  const readOnlyS = s.owner !== role && s.kind !== "signoff" && !isSources(s) && !hiddenS;
  const canPolish = s.owner === role && s.kind !== "signoff" && !isSources(s) && !hiddenS;
  const canMark = s.owner === role && s.kind !== "signoff" && !hiddenS;
  const isDone = !!status.done[s.n]?.done;
  const ownIds = pack.filter((x) => x.owner === role && x.kind !== "signoff").map((x) => x.n);
  const pending = ownIds.filter((n) => !status.done[n]?.done);
  const sendReady = pending.length === 0;
  const pendingLabel = pending.map(pos);
  const isProfile = !ips && s.n === 1;
  const sendReason = `Mark section${pendingLabel.length > 1 ? "s" : ""} ${pendingLabel.length > 1 ? `${pendingLabel.slice(0, -1).join(", ")} and ${pendingLabel[pendingLabel.length - 1]}` : pendingLabel[0]} as done to send.`;
  const allComplete = status.doneCount === status.total && status.total > 0;
  const saaRows = alloc && ips && s.chart === "saa" ? alloc : null;
  const saaParsed = saaRows ? parseSaaText(textNow) : {};
  const flagged = s.status === "flagged";
  const compareHere = compare && compare.n === s.n ? compare : null;

  const runPolish = async () => {
    setBusy(true); setPolishErr("");
    try {
      const parts = hasHeadings(textNow) ? parseBlocks(textNow) : [{ heading: undefined as string | undefined, text: textNow }];
      const skip = (h?: string) => (h ?? "").toLowerCase() === "proposed saa";
      const items = parts.flatMap((b, k) => (skip(b.heading) ? [] : [{ id: String(k), label: `${pos(s.n)}. ${s.title}${b.heading ? ` (${b.heading})` : ""}`, text: b.text }]));
      const out = await arcApi.professionalise({ clientId: realId, role, context: ips ? "ips" : "pack", items, chat: getChatContext(realId, role) });
      const byId = Object.fromEntries(out.map((o) => [o.id, o.text]));
      const merged = parts.map((b, k) => [b.heading ?? "", byId[String(k)] ?? b.text] as [string, string]);
      const newText = hasHeadings(textNow) ? composeBlocks(merged) : merged[0][1];
      setCompare({ n: s.n, oldText: textNow, newText });
    } catch {
      setPolishErr("Could not generate wording. Try again.");
    } finally {
      setBusy(false);
    }
  };
  const acceptPolish = () => {
    if (!compareHere) return;
    saveSectionBlocks(clientId, s.n, withText(blocks, compareHere.newText), role);
    setCompare(null);
  };
  const exportActions = (
    <ExportActions docTitle={ips ? "Investment Policy Statement" : "Quarterly Review Pack"} clientName={client?.name ?? realId} version={ips ? (ipsDone ? "Complete" : "Draft") : approved ? "Approved (G4)" : "Awaiting G4"} date={fmtDate(new Date().toISOString())}
      sections={sections}
      document={<PackDocument clientId={realId} workflow={workflow} clientName={client?.name ?? realId} version={ips ? (ipsDone ? "Complete" : "Draft") : approved ? "Approved (G4)" : "Awaiting G4"} pack={pack} alloc={alloc} holdings={holdingsList} approved={ips ? ipsDone : approved} />}
      exportBlocked={ips ? !ipsDone : !approved} blockedReason={ips ? "Final export unlocks once the IPS is completed." : "Final export unlocks once G4 is approved."} />
  );

  return (
    <div>
      <>
      {embedded ? (
        <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h2 className="text-3xl">{ips ? "IPS creation" : "Review pack"}</h2>
            <p className="mt-2 text-base text-ink-500">Edit the sections you own; the rest belong to {ips ? (isIc ? "the RM" : "the IC") : isIc ? "RM and PS" : "IC and PS"}.</p>
          </div>
          {!ips && <GateChip id="G4" state={approved ? "approved" : "pending"} />}
        </div>
      ) : (
        <PageHeader eyebrow={ips ? "Investment policy statement" : "Gate G4"} title={ips ? "Create the IPS" : "Review the pack"} subtitle={`Edit the sections you own; the rest belong to ${ips ? (isIc ? "the RM" : "the IC") : isIc ? "RM and PS" : "IC and PS"}.`}
          actions={ips ? undefined : <GateChip id="G4" state={approved ? "approved" : "pending"} />} />
      )}
      {!isIc && <ol className={`mb-12 grid gap-3 ${ips ? "sm:grid-cols-2" : "sm:grid-cols-3"}`} aria-label={ips ? "IPS progress" : "Review pack progress"}>
        {steps.map((st, i) => {
          const complete = ips ? (ipsBack ? true : i < stage) : i < stage;
          const current = i === activeStep;
          return (
            <li key={st.label} className="flex flex-col gap-3">
              <span className="relative h-px overflow-hidden bg-hairline-strong">
                <span className="absolute inset-y-0 left-0 h-[3px] bg-brand transition-all duration-700" style={{ width: `${complete ? 100 : i === activeStep && st.total ? (st.done / st.total) * 100 : 0}%` }} />
              </span>
              <span className="flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-ink-muted">
                {complete && <Check size={14} />}Step {i + 1}
              </span>
              <span className={`text-[18px] font-light leading-6 ${current ? "text-ink" : "text-ink-muted"}`}>{st.label}</span>
              <span className="text-[13px] text-ink-muted">{complete ? "Done" : i === activeStep ? `${st.done} of ${st.total} sections complete` : "Waiting"}</span>
            </li>
          );
        })}
      </ol>}
      {!isIc && ips && stage === 0 && (
        <NextAction title="Send to Investment Counsellor" body={sendReady ? "Send the IPS to the Investment Counsellor to propose the strategic asset allocation." : sendReason}
          action={<Button disabled={!sendReady} onClick={() => sendIpsToIc(realId)}>Send to Investment Counsellor</Button>} />
      )}
      {!isIc && ips && stage === 1 && (
        <NextAction title="Sent to Investment Counsellor" body="Waiting for the Investment Counsellor to propose the asset allocation."
          action={<Button variant="secondary" onClick={() => withdrawIpsToIc(realId)}>Withdraw</Button>} />
      )}
      {!isIc && ips && stage === 2 && (
        <NextAction title={ipsDone ? "IPS complete" : "Review and complete the IPS"} body={ipsDone ? "The IPS is complete. You can export the document." : allComplete ? "The Investment Counsellor has returned the IPS. Review every section, then complete it." : "The Investment Counsellor has returned the IPS. Review the proposal and mark your sections as done."}
          action={ipsDone ? <Button variant="secondary" onClick={() => setIpsComplete(realId, false)}>Reopen IPS</Button> : <Button disabled={!allComplete} onClick={() => setIpsComplete(realId)}>Complete IPS</Button>} />
      )}
      {!isIc && !ips && stage === 0 && (
        <NextAction title="Send to Product Specialist" body={sendReady ? "Send this client to the Product Specialist for product research." : sendReason}
          action={<Button disabled={!sendReady} onClick={() => sendReviewRequest(realId)}>Send to Product Specialist</Button>} />
      )}
      {!isIc && !ips && stage === 1 && (
        <NextAction title="Sent to Product Specialist" body="Waiting for the Product Specialist."
          action={<Button variant="secondary" onClick={() => withdrawReviewRequest(realId)}>Withdraw request</Button>} />
      )}
      {!isIc && !ips && stage === 2 && (allComplete || approved) && (
        <NextAction title={approved ? "Pack approved" : "Approve the final pack"} body={approved ? "G4 is approved. You can export the PDF." : "Approving G4 releases the PDF. The agent never approves."}
          action={approved ? undefined : <Button onClick={() => setApproved(true)}>Approve G4</Button>} />
      )}

      </>

      <div className="grid gap-8 md:grid-cols-[300px_1fr] md:items-start">
        <Card className="!p-5">
          <h2 className="text-base">Sections</h2>
          <p className="mt-1 text-xs text-ink-muted">{status.doneCount} of {sections.length} complete</p>
          <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><span className="inline-block h-3 w-5 border border-brand" />Sections you fill in</p>
          <nav className="mt-4 flex flex-col gap-2">
            {pack.map((x, idx) => {
              const done = status.complete[x.n];
              return (
                <button key={x.n} onClick={() => { setActive(x.n); setEditing(false); setCompare(null); }}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-sm border px-4 py-3.5 text-left text-sm transition-colors duration-300 ${active === x.n ? "bg-surface-inverse text-ink-inverse" : "bg-surface-100 text-ink-700 hover:bg-surface-300"} ${x.owner === role || x.kind === "signoff" ? "border-brand" : active === x.n ? "border-transparent" : "border-hairline"}`}>
                  <span className="min-w-0">
                    {idx + 1}. {x.title}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                  {done ? <Check size={16} className={`shrink-0 ${active === x.n ? "text-ink-inverse" : "text-positive"}`} aria-label="Done" /> : <X size={16} className={`shrink-0 ${active === x.n ? "text-ink-inverse" : "text-negative"}`} aria-label="Not done" />}
                  </span>
                </button>
              );
            })}
          </nav>
        </Card>

        <Card className={`min-h-96 !p-10 ${rmOwned ? "!border-brand" : ""}`}>
          <div key={active} className="animate-geneva-in space-y-8">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-[28px] font-light tracking-tight">{pos(s.n)}. {s.title}</h2>
              {rmOwned && <p className="mt-2 text-xs uppercase tracking-[0.14em] text-brand">You fill in this section</p>}
              {readOnlyS && <p className="mt-2 flex items-center gap-1.5 text-xs uppercase tracking-[0.14em] text-ink-muted"><Lock size={12} />Read only</p>}
            </div>
            <div className="flex items-center gap-3">
              {!ips && s.owner === "ic" && !isIc && <Badge tone="green">IC reviewed thoroughly</Badge>}
              {canMark && (isDone ? (
                <span className="flex items-center gap-3 text-sm text-ink-muted"><span className="flex items-center gap-1.5"><Check size={14} />Done</span>
                  <Button variant="secondary" size="sm" onClick={() => setSectionDone(clientId, s.n, false, role)}>Reopen</Button></span>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => setSectionDone(clientId, s.n, true, role)}><Check size={14} />Mark as done</Button>
              ))}
            </div>
          </div>
          {!hiddenS && icUpdated[s.n] && progress.savedAt && <p className="text-xs text-ink-muted">Updated from the IC workspace, saved {new Date(progress.savedAt).toLocaleString("en-SG", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}.</p>}
          {flagged && !hiddenS && (
            <div className="flex items-start gap-3 rounded-md bg-surface-300 p-5 text-sm text-ink">
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />Flagged line: please read this section closely before approving.
            </div>
          )}
          {hiddenS ? (
            <PendingBox owner={s.owner} />
          ) : compareHere ? (
            <WordingCompare oldText={compareHere.oldText} newText={compareHere.newText} onChangeNew={(t) => setCompare({ ...compareHere, newText: t })} onAccept={acceptPolish} onKeep={() => setCompare(null)} />
          ) : editing && canEdit && !isProfile ? (
            <BlockEditor clientId={clientId} section={s.n} blocks={blocks} onChange={(b) => saveSectionBlocks(clientId, s.n, b, role)} />
          ) : (
            <div className="text-[17px] leading-8 text-ink-700">
              {isProfile ? <ProfileCarousel clientId={clientId} blocks={blocks} canEdit={canEdit} onChange={(b) => saveSectionBlocks(clientId, 1, b, role)} />
                : saaRows ? <SaaPanel readOnly saa={{ rows: saaRows, vals: saaRows.map((r) => saaParsed[r.assetClass.toLowerCase()] ?? 0), setVals: () => undefined }} />
                : isSources(s) ? pageExtras[s.n]
                : pageExtras[s.n] ? <SectionBody n={s.n} text={textNow} extra={pageExtras[s.n]} />
                : <SectionBlocksView blocks={blocks} clientId={clientId} />}
            </div>
          )}
          {!hiddenS && !compareHere && (canEdit || canPolish || (isSources(s) && !approved)) && (
            <div className="flex flex-wrap items-center justify-between gap-4 border-t border-hairline pt-8">
              <div>{((canEdit && !isProfile) || isSources(s)) && <Button variant="secondary" onClick={() => setEditing(!editing)}>{editing ? "Done" : isSources(s) ? "Edit sources" : "Edit section"}</Button>}</div>
              {polishErr && <span className="text-xs text-negative" role="alert">{polishErr}</span>}
              {canPolish && <ProfessionaliseButton onClick={runPolish} loading={busy} label="Professionalise" />}
            </div>
          )}
          </div>
        </Card>
      </div>

      <div className="mt-10 flex flex-wrap justify-end">{exportActions}</div>
    </div>
  );
}
