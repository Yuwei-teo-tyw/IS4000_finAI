import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Check, Lock, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, useAsync } from "../../components/ui";
import { ProfileCarousel, ProfileEdit, SectionBlocksView, SectionBody, WordingCompare, composeProfile, packToSections, parseProfile, parseSaaLines, useSeededBlocks, withText, primaryText, fmtDate, SignoffBoxes, SourcesBoard, isSources, usePackStatus, isHiddenFor, PendingBox } from "./rmShared";
import { hasHeadings, parseBlocks, composeBlocks } from "../../services/packBlocks";
import { PackDocument } from "./PackDocument";
import { syncPackFromIc } from "../../components/ic/packSync";
import { BlockEditor, saveSectionBlocks } from "../../components/documents/pack";
import { loadPackDrafts, loadSignatures, saveSignature, setSectionDone, subscribePackDrafts, subscribeSignatures, type PackDrafts, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { sendReviewRequest, withdrawReviewRequest, useReviewRequest, useAllFinalised, useIcProgress } from "../../services/workflowStore";
import { useRole } from "../../layouts/AppShell";
import { ProfessionaliseButton } from "../../components/geneva/ProfessionaliseButton";
import { getChatContext } from "../../services/chatContextStore";
import { ExportActions } from "../../components/export/ExportActions";

export default function PackReview({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const role = useRole();
  const isIc = role === "ic";
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [active, setActive] = useState(1);
  const [drafts, setDrafts] = useState<PackDrafts>(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState<Sigs>(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const progress = useIcProgress(clientId);
  const holdingsList = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const [editing, setEditing] = useState(false);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [compare, setCompare] = useState<{ n: number; oldText: string; newText: string } | null>(null);
  const [saaDraft, setSaaDraft] = useState<number[] | null>(null);
  const [proposed, setProposed] = useState(false);
  const [polishErr, setPolishErr] = useState("");
  const sent = useReviewRequest(clientId);
  const finalisedByPs = useAllFinalised().some((f) => f.clientId === clientId);
  /** 0 = RM updates, 1 = waiting on Product Specialist, 2 = with IC. */
  const stage = finalisedByPs ? 2 : sent ? 1 : 0;
  const status = usePackStatus(clientId);
  const needSync = !!progress.savedAt && drafts[4] === undefined;
  useEffect(() => { if (needSync) syncPackFromIc(clientId); }, [needSync, clientId]);
  const sec0 = pack?.find((x) => x.n === active);
  const onboarding = client?.status === "Onboarding Phase";
  const blocks = useSeededBlocks(clientId, active, sec0?.body ?? "", sec0?.chart, onboarding && sec0?.chart === "saa");
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
    ...(sourcesN ? { [sourcesN]: <SourcesBoard clientId={clientId} me={role} editing={editing} hideEditButton /> } : {}),
  };
  const sections = packToSections(clientId, pack, drafts, touched, pageExtras).map((x) => ({ ...x, complete: !!status.complete[x.n], ...(isHiddenFor(x, role, status.complete) && !isSources(x) ? { body: <PendingBox owner={x.owner} /> } : {}) }));
  const steps = [
    { label: "RM Updates", owner: "rm" },
    { label: "Product Specialist Recommendations", owner: "ps" },
    { label: "IC Portfolio Allocation", owner: "ic" },
  ].map((st) => {
    const mine = sections.filter((x) => x.owner === st.owner);
    return { ...st, done: mine.filter((x) => x.complete).length, total: mine.length };
  });
  const activeStep = stage;
  const s = pack.find((x) => x.n === active)!;
  const textNow = primaryText(blocks);
  const canEdit = s.owner === role && s.kind !== "signoff" && !isSources(s) && !approved;
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
  const sendReason = `Mark section${pendingLabel.length > 1 ? "s" : ""} ${pendingLabel.length > 1 ? `${pendingLabel.slice(0, -1).join(", ")} and ${pendingLabel[pendingLabel.length - 1]}` : pendingLabel[0]} as done to send.`;
  const allComplete = status.doneCount === status.total && status.total > 0;
  const flagged = s.status === "flagged";
  const compareHere = compare && compare.n === s.n ? compare : null;

  const saaRows = alloc ?? [];
  const proposal = parseSaaLines(parseProfile(textNow).saa);
  const saaVals = saaDraft ?? saaRows.map((r) => proposal[r.assetClass] ?? r.saa);
  const saaTotal = Math.round(saaVals.reduce((a, b) => a + b, 0) * 10) / 10;
  const showSaa = onboarding && s.n === 1 && !!alloc;
  const proposeSaa = () => {
    const cur = parseProfile(textNow);
    const lines = saaRows.map((r, i) => `${r.assetClass}: ${saaVals[i]}%`).join("\n");
    saveSectionBlocks(clientId, 1, withText(blocks, composeProfile({ ...cur, saa: lines })), role);
    setProposed(true);
  };

  const runPolish = async () => {
    setBusy(true); setPolishErr("");
    try {
      const parts = hasHeadings(textNow) ? parseBlocks(textNow) : [{ heading: undefined as string | undefined, text: textNow }];
      const skip = (h?: string) => (h ?? "").toLowerCase() === "proposed saa";
      const items = parts.flatMap((b, k) => (skip(b.heading) ? [] : [{ id: String(k), label: `${pos(s.n)}. ${s.title}${b.heading ? ` (${b.heading})` : ""}`, text: b.text }]));
      const out = await arcApi.professionalise({ clientId, role, context: "pack", items, chat: getChatContext(clientId, role) });
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
          const complete = i < stage;
          const current = i === activeStep;
          return (
            <li key={st.label} className="flex flex-col gap-3">
              <span className="relative h-px overflow-hidden bg-hairline-strong">
                <span className="absolute inset-y-0 left-0 h-[3px] bg-brand transition-all duration-700" style={{ width: `${complete ? 100 : i === stage && st.total ? (st.done / st.total) * 100 : 0}%` }} />
              </span>
              <span className="flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-ink-muted">
                {complete && <Check size={14} />}Step {i + 1}
              </span>
              <span className={`text-[18px] font-light leading-6 ${current ? "text-ink" : "text-ink-muted"}`}>{st.label}</span>
              <span className="text-[13px] text-ink-muted">{complete ? "Done" : i === stage ? `${st.done} of ${st.total} sections complete` : "Waiting"}</span>
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
              {s.owner === "ic" && !isIc && <Badge tone="green">IC reviewed thoroughly</Badge>}
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
          ) : editing && canEdit ? (
            s.n === 1 ? (
              <ProfileEdit key={clientId} clientId={clientId} blocks={blocks} onChange={(b) => saveSectionBlocks(clientId, 1, b, role)} />
            ) : (
              <BlockEditor clientId={clientId} section={s.n} blocks={blocks} onChange={(b) => saveSectionBlocks(clientId, s.n, b, role)} />
            )
          ) : (
            <div className="text-[17px] leading-8 text-ink-700">
              {s.n === 1 ? <ProfileCarousel clientId={clientId} blocks={blocks} saa={showSaa ? { rows: saaRows, vals: saaVals, setVals: setSaaDraft } : undefined} />
                : isSources(s) ? pageExtras[s.n]
                : pageExtras[s.n] ? <SectionBody n={s.n} text={textNow} extra={pageExtras[s.n]} />
                : <SectionBlocksView blocks={blocks} clientId={clientId} />}
            </div>
          )}
          {!hiddenS && !compareHere && (canEdit || canPolish || (isSources(s) && !approved)) && (
            <div className="flex flex-wrap items-center justify-between gap-4 border-t border-hairline pt-8">
              <div>{(canEdit || isSources(s)) && <Button variant="secondary" onClick={() => setEditing(!editing)}>{editing ? "Done" : isSources(s) ? "Edit sources" : "Edit section"}</Button>}</div>
              {polishErr && <span className="text-xs text-negative" role="alert">{polishErr}</span>}
              {showSaa && canPolish ? (
                <span className="flex items-center gap-4">
                  {proposed && <span className="text-xs text-ink-muted" role="status">Proposed SAA saved</span>}
                  <Button disabled={saaTotal !== 100} onClick={proposeSaa}>Propose SAA</Button>
                </span>
              ) : canPolish && <ProfessionaliseButton onClick={runPolish} loading={busy} label="Professionalise" />}
            </div>
          )}
          </div>
        </Card>
      </div>

      <div className="mt-10 flex flex-wrap justify-end">{exportActions}</div>
    </div>
  );
}
