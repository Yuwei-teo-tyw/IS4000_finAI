import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Check } from "lucide-react";
import { arcApi, type PackCheckInput } from "../../services/arcApi";
import { Badge, Button, GateChip, Loading, NextAction, PageHeader, useAsync, useAsyncResult } from "../../components/ui";
import { packToSections, fmtDate, SignoffBoxes, SourcesBoard, isSources, usePackStatus, isHiddenFor, PendingBox } from "./rmShared";
import { PackSectionPanel } from "./PackSectionPanel";
import { GenevaMark } from "../../components/documents/GenevaMark";
import { PackDocument } from "./PackDocument";
import { syncPackFromPm } from "../../components/pm/packSync";
import { loadPackDrafts, loadSignatures, saveSignature, subscribePackDrafts, subscribeSignatures, type PackDrafts, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { sendReviewRequest, withdrawReviewRequest, useReviewRequest, useAllFinalised, useFinalised, usePmProgress, usePmHandover } from "../../services/workflowStore";
import { useRole } from "../../layouts/AppShell";
import { ExportActions } from "../../components/export/ExportActions";
import type { RcPackReport } from "../../types/riskCompliance";

type PackCheck = { running: boolean; report?: RcPackReport; error?: string } | null;

export default function PackReview({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const role = useRole();
  const isPm = role === "pm";
  const [packTry, setPackTry] = useState(0);
  const { data: pack, error: packError } = useAsyncResult(() => arcApi.getPack(clientId), [clientId, packTry]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [drafts, setDrafts] = useState<PackDrafts>(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState<Sigs>(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const progress = usePmProgress(clientId);
  const holdingsList = useAsync(() => arcApi.getHoldings(clientId), [clientId]);
  const [approved, setApproved] = useState(false);
  const sent = useReviewRequest(clientId);
  const finalisedByPs = useAllFinalised().some((f) => f.clientId === clientId);
  /** 0 = RM updates, 1 = waiting on Product Specialist, 2 = with PM. */
  const stage = finalisedByPs ? 2 : sent ? 1 : 0;
  const status = usePackStatus(clientId);
  const pmHandover = usePmHandover(clientId);
  // Keep sections 4 and 8 in step with the PM's saved values: on mount, on every PM save and when the PM hands over.
  useEffect(() => { if (progress.savedAt || pmHandover) syncPackFromPm(clientId); }, [progress.savedAt, pmHandover?.sentAt, clientId]);
  const [openMap, setOpenMap] = useState<Record<number, boolean>>({});
  const onboarding = client?.status === "Onboarding Phase";
  // Risk & Compliance agent: final independent check of the whole pack before G4. It re-runs whenever
  // what it reads changes; G4 stays locked unless it allows sign-off (and while it cannot run).
  const finalised = useFinalised(clientId);
  const [check, setCheck] = useState<PackCheck>(null);
  const [checkRun, setCheckRun] = useState(0);
  const readyForG4 = !isPm && stage === 2 && status.total > 0 && status.doneCount === status.total && !approved;
  const savedNewTaa = alloc && progress.taa && progress.taa.length === alloc.length ? progress.taa : null;
  const checkInput: PackCheckInput | null = readyForG4 && pack && alloc ? {
    clientId,
    sections: pack.map((x) => ({
      n: x.n, title: x.title, owner: x.owner, gate: x.gate, kind: x.kind ?? null, text: drafts[x.n] ?? x.body,
      status: status.complete[x.n] ? "ready" : x.status === "flagged" ? "flagged" : "draft",
    })),
    allocation: alloc.map((r, i) => (savedNewTaa ? { ...r, newTaa: savedNewTaa[i] } : r)),
    products: (finalised?.items ?? []).map((it) => ({ name: it.product, assetClass: it.assetClass })),
    // G1 = an active IPS, which only the derived Monitoring phase proves (an ipsVersion alone may be a draft).
    gates: { G1: client?.status === "Monitoring Phase" ? "approved" : "pending", G2: pmHandover ? "approved" : "pending", G3: finalised ? "approved" : "pending", G4: "pending" },
  } : null;
  // Keyed on the serialised input: the store hooks return new objects every render, so this re-runs only when the pack really changes.
  const checkKey = checkInput ? JSON.stringify(checkInput) : "";
  useEffect(() => {
    if (!checkKey) { setCheck(null); return; }
    let cancelled = false;
    setCheck({ running: true });
    arcApi.checkReviewPack(JSON.parse(checkKey) as PackCheckInput)
      .then((report) => { if (!cancelled) setCheck({ running: false, report }); })
      .catch((e: unknown) => { if (!cancelled) setCheck({ running: false, error: e instanceof Error ? e.message : "The check could not run." }); });
    return () => { cancelled = true; };
  }, [checkKey, checkRun]);
  if (packError) {
    return (
      <div className="border border-hairline bg-surface-100 p-8" role="alert">
        <p className="text-base text-ink">The review pack could not be loaded.</p>
        <p className="mt-2 text-sm text-ink-muted">Check your connection and try again.</p>
        <div className="mt-5"><Button variant="ghost" onClick={() => setPackTry((n) => n + 1)}>Retry</Button></div>
      </div>
    );
  }
  if (!pack) return <Loading />;
  if (pack.length === 0) {
    return (
      <div>
        {embedded ? <h2 className="text-3xl">Review pack</h2> : <PageHeader title="Review the pack" />}
        <p className="mt-6 text-base text-ink-muted">No review pack yet. It will appear here once a quarterly review starts.</p>
      </div>
    );
  }
  const pos = (n: number) => pack.findIndex((x) => x.n === n) + 1;
  const allSigned = ["ps", "pm", "rm"].every((r) => sigs[r]);
  const signoffN = pack.find((x) => x.kind === "signoff")?.n;
  const sourcesN = pack.find(isSources)?.n;
  const touched = [...Object.keys(drafts).map(Number).filter((n) => n !== signoffN), ...(allSigned && signoffN ? [signoffN] : [])];
  const savedTaa = alloc && progress.taa && progress.taa.length === alloc.length ? progress.taa : null;
  const editedHoldings = progress.holdings && Object.keys(progress.holdings).length > 0 ? progress.holdings : null;
  const pmUpdated: Record<number, boolean> = { 4: !!savedTaa, 8: !!editedHoldings };
  const pageExtras: Record<number, React.ReactNode> = {
    ...(signoffN ? { [signoffN]: <SignoffBoxes sigs={sigs} me={role} clientId={clientId} onRemove={(r) => saveSignature(clientId, r, null)} /> } : {}),
    ...(sourcesN ? { [sourcesN]: <SourcesBoard clientId={clientId} me={role} editing={false} hideEditButton /> } : {}),
  };
  const sections = packToSections(clientId, pack, drafts, touched, pageExtras).map((x) => ({ ...x, complete: !!status.complete[x.n], ...(isHiddenFor(x, role, status.complete) && !isSources(x) ? { body: <PendingBox owner={x.owner} /> } : {}) }));
  const steps = [
    { label: "RM Updates", owner: "rm" },
    { label: "Product Specialist Recommendations", owner: "ps" },
    { label: "PM Portfolio Allocation", owner: "pm" },
  ].map((st) => {
    const mine = sections.filter((x) => x.owner === st.owner && x.n !== signoffN);
    const done = mine.filter((x) => x.complete).length;
    const gate = st.owner === "rm" ? sent || finalisedByPs : st.owner === "ps" ? finalisedByPs : !!pmHandover;
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
  const updatedNote = (n: number) => (pmUpdated[n] && progress.savedAt ? `Updated from the PM workspace, saved ${new Date(progress.savedAt).toLocaleString("en-SG", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}.` : undefined);
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
            <p className="mt-2 text-base text-ink-500">Edit the sections you own; the rest belong to {isPm ? "RM and PS" : "PM and PS"}.</p>
          </div>
          <GateChip id="G4" state={approved ? "approved" : "pending"} />
        </div>
      ) : (
        <PageHeader eyebrow="Gate G4" title="Review the pack" subtitle={`Edit the sections you own; the rest belong to ${isPm ? "RM and PS" : "PM and PS"}.`}
          actions={<GateChip id="G4" state={approved ? "approved" : "pending"} />} />
      )}
      {!isPm && <ol className="mb-12 grid gap-3 sm:grid-cols-3" aria-label="Review pack progress">
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
      {!isPm && stage === 0 && !onboarding && (
        <NextAction title="Send to Product Specialist" body={sendReady ? "Send this client to the Product Specialist for product research." : sendReason}
          action={<Button disabled={!sendReady} onClick={() => sendReviewRequest(clientId)}>Send to Product Specialist</Button>} />
      )}
      {!isPm && stage === 1 && (
        <NextAction title="Sent to Product Specialist" body="Waiting for the Product Specialist."
          action={<Button variant="secondary" onClick={() => withdrawReviewRequest(clientId)}>Withdraw request</Button>} />
      )}
      {!isPm && stage === 2 && (allComplete || approved) && (
        <NextAction title={approved ? "Pack approved" : "Approve the final pack"} body={approved ? "G4 is approved. You can export the PDF." : g4Body(check)}
          action={approved ? undefined : <Button disabled={!check?.report?.rm_signoff_allowed} onClick={() => setApproved(true)}>Approve G4</Button>} />
      )}
      {!isPm && stage === 2 && allComplete && !approved && check && !check.running && (
        <PackCheckPanel check={check} onRerun={() => setCheckRun((n) => n + 1)} />
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

/** NextAction text for G4, driven by the Risk & Compliance check. */
function g4Body(check: PackCheck): string {
  if (!check || check.running) return "Running the risk & compliance check. G4 unlocks once it allows sign-off.";
  if (check.error) return `The risk & compliance check could not run, so G4 stays locked. ${check.error}`;
  const r = check.report!;
  if (!r.rm_signoff_allowed) return "G4 is locked: the risk & compliance check found issues to resolve first.";
  return r.status === "PASS_WITH_CONDITIONS"
    ? "Review the conditions below, then approve. Approving G4 releases the PDF. The agent never approves."
    : "Approving G4 releases the PDF. The agent never approves.";
}

const STATUS_LABEL: Record<RcPackReport["status"], { text: string; tone: "green" | "amber" | "red" }> = {
  PASS: { text: "Passed", tone: "green" },
  PASS_WITH_CONDITIONS: { text: "Passed with conditions", tone: "amber" },
  NEEDS_INFO: { text: "Needs information", tone: "amber" },
  BLOCKED: { text: "Blocked", tone: "red" },
};
const ITEM_LABEL = { block: "Blocks", info: "Needs info", condition: "Condition" } as const;

/** The check's result: everything that blocks or conditions sign-off. Notes are counted, not listed. */
function PackCheckPanel({ check, onRerun }: { check: NonNullable<PackCheck>; onRerun: () => void }) {
  const r = check.report;
  const items: { key: string; kind: keyof typeof ITEM_LABEL; text: string }[] = r ? [
    ...r.findings.filter((f) => f.effect !== "NOTE").map((f, i) => ({
      key: `f${i}`, kind: (f.effect === "BLOCK" ? "block" : f.effect === "NEEDS_INFO" ? "info" : "condition") as keyof typeof ITEM_LABEL, text: f.message,
    })),
    ...r.missing_information.filter((m) => m.severity !== "MINOR").map((m, i) => ({
      key: `m${i}`, kind: (m.severity === "BLOCKING" ? "info" : "condition") as keyof typeof ITEM_LABEL, text: `${m.field}: ${m.impact}`,
    })),
    ...r.conflicts.filter((c) => c.severity !== "INFO").map((c, i) => ({
      key: `c${i}`, kind: (c.severity === "BLOCKING" ? "block" : "condition") as keyof typeof ITEM_LABEL, text: c.description,
    })),
  ] : [];
  const notes = r ? r.findings.filter((f) => f.effect === "NOTE").length : 0;
  return (
    <section className="mb-14" aria-label="Risk and compliance check">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h3 className="text-xl font-light">Risk &amp; compliance check</h3>
          {r && <Badge tone={STATUS_LABEL[r.status].tone}>{STATUS_LABEL[r.status].text}</Badge>}
        </div>
        <Button variant="secondary" size="sm" onClick={onRerun}>Run check again</Button>
      </div>
      {check.error && <p className="text-sm text-negative">{check.error}</p>}
      {r && items.length === 0 && <p className="text-sm text-ink-muted">No issues found.</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-hairline border-y border-hairline">
          {items.map((it) => (
            <li key={it.key} className="flex items-start gap-4 py-3 text-sm">
              <Badge tone={it.kind === "block" ? "red" : "amber"}>{ITEM_LABEL[it.kind]}</Badge>
              <span className="leading-6">{it.text}</span>
            </li>
          ))}
        </ul>
      )}
      {r && (
        <p className="mt-3 text-xs text-ink-muted">
          {notes > 0 ? `${notes} note${notes > 1 ? "s" : ""} recorded. ` : ""}Policy {r.policy_version ?? "unavailable"}. The agent checks; only the RM approves G4.
        </p>
      )}
    </section>
  );
}
