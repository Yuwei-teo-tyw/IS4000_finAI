import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Eye } from "lucide-react";
import { Button, GateChip, Loading, PageHeader, Stepper, useAsync } from "../../components/ui";
import { onboardingSteps } from "./rmShared";
import { getIpsDraftExtras, saveIpsDraftExtras, useIpsDraftExtras, sendIpsToPm, useIpsSent, useIpsReturned, withdrawIpsFromPm } from "../../services/workflowStore";
import { IpsSendError } from "../../services/arcApi";
import { ConfirmDialog, IpsStatusBadge } from "./IpsSendUi";
import { findEmptySections, formatSentAt, useIpsSendStatus, type IpsStatusLabel } from "./ipsSendUtil";
import { IpsDocument, type IpsEditApi } from "../../components/documents/IpsDocument";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import type { Bucket3L, IpsGenerated, IpsVersion, ThreeLProportion } from "../../types/arc";
import { useIpsAutosave } from "../../components/documents/ips/useIpsAutosave";
import { buildIpsData, seedFromData, type IpsSeed } from "../../components/documents/ips/ipsData";
import type { ThreeLMeta } from "../../components/documents/ips/Allocation";
import { IpsEditPopover, type PopoverTarget } from "../../components/geneva/IpsEditPopover";

const RM_PARTS = [1, 3, 5, 6];

/** `version`: edit this saved version (a Draft is edited in place; saves reuse its number). Without it the newest Draft, else the current IPS, is opened. */
export default function IpsDraft({ embedded = false, clientId: clientIdProp, blank = false, generated, version: versionProp }: { embedded?: boolean; clientId?: string; blank?: boolean; generated?: IpsGenerated; version?: number }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const nav = useNavigate();
  /** The saved backend version (with its structured `data`) when there is one; otherwise the mock/blank parts. */
  const src = useAsync(async () => {
    if (blank) return { rec: null, parts: await arcApi.getBlankIpsParts() };
    const rec = await arcApi.getIpsVersionRecord(clientId, versionProp);
    return { rec, parts: rec ? rec.parts : await arcApi.getIps(clientId) };
  }, [clientId, blank, versionProp]);
  const parts = src?.parts;
  const rec = src?.rec ?? null;
  const seed = useMemo<IpsSeed | null>(() => (rec?.data ? seedFromData(rec.data) : null), [rec]);
  const [notIncluded, setNotIncluded] = useState<string[]>([]);
  const [allocationMeta0, setAllocationMeta0] = useState<Partial<Record<"liquidity" | "longevity" | "legacy", ThreeLMeta>>>({});
  const [proposed0, setProposed0] = useState<Partial<Record<"liquidity" | "longevity" | "legacy", string>>>({});
  const [pop, setPop] = useState<(PopoverTarget & { id: number }) | null>(null);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const buckets0 = useAsync(() => (blank ? arcApi.getBlank3L() : arcApi.get3L(clientId)), [clientId, blank]);
  const [text, setText] = useState<Record<number, string>>({});
  const [buckets, setBuckets] = useState<Bucket3L[]>([]);
  const storeExtras = useIpsDraftExtras(clientId);
  const [demo, setDemo] = useState<Record<string, string>>({});
  const [risk, setRisk] = useState<Record<string, string>>({});
  const [philosophy, setPhilosophy] = useState<{ approach?: string; believes?: string; avoids?: string; statement?: string; investmentPeriod?: string }>({});
  const [allocation, setAllocation] = useState<{ liquidity?: string; longevity?: string; legacy?: string }>({});
  const [allocationNotes, setAllocationNotes] = useState<Record<string, string>>({});
  const [proportion, setProportion] = useState<ThreeLProportion | null>(null);
  const [proportionNote, setProportionNote] = useState<{ message?: string; missing?: string[] }>({});
  const [signatures, setSignatures] = useState<{ client?: string; rm?: string }>({});
  const hydrated = useRef(false);
  const [previewing, setPreviewing] = useState(false);
  const sentRec = useIpsSent(clientId);
  const sent = !!sentRec;
  const returnedLocal = useIpsReturned(clientId);
  const { status: sendStatus, refresh: refreshSend } = useIpsSendStatus(clientId);
  const [dlg, setDlg] = useState<{ kind: "send" | "withdraw"; empties: string[]; error?: string; busy?: boolean } | null>(null);
  const [dismissedOutdated, setDismissedOutdated] = useState<number | null>(null);
  const seq = useRef(0);
  const [saveMsg, setSaveMsg] = useState<{ tone: "ok" | "pending" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const saveRef = useRef<() => Promise<void>>(async () => {});  // throws when the save fails (autosave shows the error)
  const savedVersion = useRef<number | undefined>(undefined);
  const loggedOverrides = useRef<Set<string>>(new Set());
  const saveChain = useRef<Promise<void>>(Promise.resolve());
  /** Geneva's original proposal per bucket (before the Liquidity A-B clamp), for override detection. */
  const proposedAllocation = useMemo(() => ({ ...(Object.fromEntries((generated?.allocation?.buckets ?? []).map((b) => [b.id, b.strategy])) as Partial<Record<"liquidity" | "longevity" | "legacy", string>>), ...proposed0 }), [generated, proposed0]);
  const allocationMeta = useMemo(() => ({ ...Object.fromEntries((generated?.allocation?.buckets ?? []).map((b) => [b.id, { strategy: b.strategy, reason: b.justification }])), ...allocationMeta0 }), [generated, allocationMeta0]);
  // A saved backend version (generated or edited before) is autosaved in place; a client-side-only generated draft saves once at once.
  const autosave = useIpsAutosave({ ready: hydrated.current && (!!generated || savedVersion.current !== undefined), signature: JSON.stringify([proportion, text, buckets, demo, risk, philosophy, allocation, allocationNotes, signatures, notIncluded, storeExtras.targets, storeExtras.rmSignedDate]), save: () => saveRef.current(), immediate: !!generated && !rec });
  useEffect(() => {
    if (!parts) return;
    // Part 5 once carried an appended "3L's Strategic Asset Allocations" (formerly "3L strategy allocation") block; keep it out of the review-rules editor.
    const t: Record<number, string> = Object.fromEntries(parts.map((p) => [p.part, p.part === 5 ? p.body.replace(/\n*3L(?: strategy allocation|'s Strategic Asset Allocations)\n[\s\S]*$/, "") : p.body]));
    if (generated?.text[1]) t[1] = generated.text[1];
    if (generated?.text[3]) t[3] = generated.text[3];
    // Backend `parts` are lossy text renders; the structured `data` is the truth for goals, loss tolerance and review rules.
    if (seed) Object.assign(t, seed.text);
    setText(t);
    // Reuse the saved Draft (or the explicitly opened version) so saves update it instead of piling up versions.
    if (rec && savedVersion.current === undefined && (rec.status === "Draft" || versionProp === rec.version)) savedVersion.current = rec.version;
  }, [parts, generated, seed, rec, versionProp]);
  useEffect(() => {
    if (!buckets0 || !src || hydrated.current) return;
    const x = getIpsDraftExtras(clientId);
    setBuckets(x.buckets ?? buckets0);
    const empty = (o?: object) => !o || Object.values(o).every((v) => !v);
    if (seed) {
      // Saved backend data wins over stale local extras; it already holds every edit that was autosaved.
      setDemo(seed.demo); setRisk(seed.risk); setPhilosophy(seed.philosophy);
      const sigRm = seed.rmSignatureImage && seed.rmSignatureImage !== "/signature-isabel.png" ? seed.rmSignatureImage : undefined;
      setSignatures({ ...(x.signatures ?? {}), ...(sigRm && x.signatures?.rm === undefined ? { rm: sigRm } : {}) });
      setProportion(seed.proportion ?? generated?.proportion ?? null); setProportionNote({ message: seed.proportionMessage, missing: generated?.proportionMissing });
      setNotIncluded(seed.notIncluded); setAllocationMeta0(seed.allocationMeta); setProposed0(seed.proposed);
      saveIpsDraftExtras(clientId, { targets: seed.targets, reviewRules: seed.reviewRules, ...(seed.rmSignedDate ? { rmSignedDate: seed.rmSignedDate } : {}), allocation: seed.allocation, allocationNotes: seed.allocationNotes });
      if (Object.keys(seed.allocation).length) { setAllocation(seed.allocation); setAllocationNotes(seed.allocationNotes); }
      else { setAllocation({}); setAllocationNotes({}); }
    } else {
      setDemo(!empty(x.demo) ? x.demo! : generated?.demo ?? {}); setRisk(!empty(x.risk) ? x.risk! : generated?.risk ?? {}); setPhilosophy(!empty(x.philosophy) ? x.philosophy! : generated?.philosophy ?? {}); setSignatures(x.signatures ?? {});
    }
    if (!seed) { setProportion(generated?.proportion ?? null); setProportionNote({ missing: generated?.proportionMissing }); }
    if (!seed) {
      const fixLiq = (a: { liquidity?: string; longevity?: string; legacy?: string }) => ({ ...a, ...(a.liquidity && !["A", "B"].includes(a.liquidity) ? { liquidity: "B" } : {}) });
      const hasA = x.allocation && Object.values(x.allocation).some(Boolean);
      if (hasA) { setAllocation(fixLiq(x.allocation!)); setAllocationNotes(x.allocationNotes ?? {}); }
      else {
        const a: Record<string, string> = {}, n: Record<string, string> = {};
        for (const b of generated?.allocation?.buckets ?? []) { a[b.id] = b.strategy; n[b.id] = b.justification; }
        setAllocation(fixLiq(a)); setAllocationNotes(n);
      }
    }
    hydrated.current = true;
  }, [buckets0, clientId, src, seed]);
  useEffect(() => { if (hydrated.current && buckets.length) saveIpsDraftExtras(clientId, { buckets, demo, risk, philosophy, allocation, allocationNotes, signatures }); }, [buckets, demo, risk, philosophy, allocation, allocationNotes, signatures, clientId]);
  /** Geneva's confirmed allocation change (written to the store by the chat) flows into the editor and is autosaved from there. */
  useEffect(() => {
    if (!hydrated.current) return;
    const a = storeExtras.allocation, n = storeExtras.allocationNotes;
    if (a) setAllocation((c) => JSON.stringify(c) === JSON.stringify(a) ? c : a);
    if (n) setAllocationNotes((c) => JSON.stringify(c) === JSON.stringify(n) ? c : n);
  }, [storeExtras.allocation, storeExtras.allocationNotes]);
  const version = useMemo<IpsVersion | null>(() => parts ? {
    version: rec?.version ?? 0, issuedOn: rec?.issuedOn ?? new Date().toISOString(), status: "Draft", author: "Relationship Manager", summary: "Onboarding draft", parts,
  } : null, [parts, rec]);
  if (!parts || !version || !buckets0 || !hydrated.current) return <Loading />;
  const api: IpsEditApi = { text, setText: (n, v) => setText((t) => ({ ...t, [n]: v })), buckets, setBuckets,
    demo, setDemo: (l, v) => setDemo((d) => ({ ...d, [l]: v })),
    risk, setRisk: (l, v) => setRisk((d) => ({ ...d, [l]: v })),
    philosophy, setPhilosophy: (k, v) => setPhilosophy((d) => ({ ...d, [k]: v })),
    allocation, allocationNotes, proposedAllocation, allocationMeta, notIncluded, setNotIncluded, outOfDate: seed?.outOfDate,
    proportion, proportionMessage: proportionNote.message, proportionMissing: proportionNote.missing,
    setProportionPct: (k, n) => setProportion((p) => p ? { ...p, [k]: { ...p[k], pct: Number.isFinite(n) ? Math.max(0, n) : 0 } } : p),
    setAllocationNote: (b, t) => setAllocationNotes((n) => ({ ...n, [b]: t })),
    setAllocation: (b, c) => setAllocation((a) => ({ ...a, [b]: b === "liquidity" && !["A", "B"].includes(c) ? "B" : c })),
    signatures, setSignature: (who, url) => setSignatures((g) => ({ ...g, [who]: url })),
  };
  const previewVersion: IpsVersion = { ...version, parts: parts.map((p) => ({ ...p, body: [1, 3, 5].includes(p.part) ? (text[p.part] ?? p.body) : p.body })) };
  const openPreview = () => {
    saveIpsDraftExtras(clientId, { buckets, demo, risk, philosophy, allocation, allocationNotes, signatures });
    setPreviewing(true);
  };
  const previewBtn = (
    <Button variant="ghost" size="sm" onClick={openPreview}><Eye size={16} className="mr-2" aria-hidden />Preview IPS document</Button>
  );
  const subtitle = `You fill ${RM_PARTS.map((n) => parts.find((x) => x.part === n)?.title ?? "").filter(Boolean).join(", ")}.`;

  const STRAT: Record<string, string> = { A: "Fixed Income", B: "Income", C: "Yield", D: "Balanced", E: "Growth", F: "Equities" };
  const allocationText = (): string => {
    const lines = (["liquidity", "longevity", "legacy"] as const).filter((b) => allocation[b]).map((b) => {
      const code = allocation[b]!;
      const name = generated?.allocation?.buckets.find((g) => g.id === b && g.strategy === code)?.strategyName ?? STRAT[code] ?? "";
      return `${b[0].toUpperCase()}${b.slice(1)} portfolio: Strategy ${code} - ${name}.${allocationNotes[b] ? ` ${allocationNotes[b]}` : ""}`;
    });
    return lines.length ? `3L's Strategic Asset Allocations\n${lines.join("\n")}` : "";
  };
  const withAlloc = (body: string) => {
    const a = allocationText();
    return a ? `${body.replace(/\n*3L(?: strategy allocation|'s Strategic Asset Allocations)\n[\s\S]*$/, "").trimEnd()}\n\n${a}` : body;
  };

  /** Save the IPS to the database (a new version the first time, then the same version); the backend vectorizes it and tells us whether it is searchable yet.
   *  Saves are chained, never parallel: an autosave and a click on Save IPS must not both create "the first version". */
  const saveIps = (): Promise<boolean> => {
    const run = async () => {
      // A strategy different from Geneva's proposal needs the RM's own reason; it is logged for future reference.
      const overrides = (["liquidity", "longevity", "legacy"] as const).filter((b) => allocation[b] && proposedAllocation[b] && allocation[b] !== proposedAllocation[b]);
      const noReason = overrides.filter((b) => { const r = (allocationNotes[b] ?? "").trim(); return !r || r === (allocationMeta[b]?.reason ?? "").trim(); });
      if (noReason.length) {
        setSaveMsg({ tone: "error", text: `Give a reason before saving: ${noReason.map((b) => `${b} Strategy ${allocation[b]} instead of Geneva's Strategy ${proposedAllocation[b]}`).join("; ")}.` });
        return false;
      }
      for (const b of overrides) {
        const key = `${b}|${allocation[b]}|${allocationNotes[b]!.trim()}`;
        if (loggedOverrides.current.has(key)) continue;
        loggedOverrides.current.add(key);
        void arcApi.logStrategyOverride({ clientId, bucket: b, proposed: proposedAllocation[b], chosen: allocation[b]!, reason: allocationNotes[b]!.trim() });
      }
      if (proportion) {
        const v = await arcApi.validateThreeLProportion({ liquidity: proportion.liquidity.pct, longevity: proportion.longevity.pct, legacy: proportion.legacy.pct });
        if (!v.ok) { setSaveMsg({ tone: "error", text: `${v.message || `Total is ${v.total}%, not 100%.`} Fix the 3L proportion in section 5 before saving.` }); return false; }
      }
      setSaving(true); setSaveMsg(null);
      try {
        const x = getIpsDraftExtras(clientId);
        const table = await arcApi.getStrategies().then((r) => r.strategies).catch(() => []);
        const rateOfReturn = Object.fromEntries((["liquidity", "longevity", "legacy"] as const).flatMap((b) => {
          const t = table.find((s) => s.code === allocation[b])?.rateOfReturnText?.trim();
          return t ? [[b, t]] : [];
        }));
        const data = buildIpsData(rec?.data, {
          rateOfReturn,
          text, targets: x.targets, demo, risk, philosophy, allocation, allocationNotes,
          allocationMeta, notIncluded, proportion, rmSignedDate: x.rmSignedDate, rmSignature: signatures.rm,
        });
        const out = await arcApi.saveClientIps(
          clientId,
          parts.map((p) => ({ part: p.part, title: p.title, owner: p.owner, status: p.status, body: p.part === 5 ? withAlloc(text[5] ?? p.body) : [1, 3].includes(p.part) ? (text[p.part] ?? p.body) : p.body })),
          { author: "Relationship Manager", summary: blank ? "Onboarding IPS" : undefined, version: savedVersion.current, data,
            ...(savedVersion.current === undefined && (blank || !!generated) ? { status: "Draft" as const } : {}) },
        );
        savedVersion.current = out.version;
        void refreshSend();
        setSaveMsg({ tone: out.indexing.status === "indexed" ? "ok" : "pending", text: out.indexing.message });
        return true;
      } catch (e) {
        setSaveMsg({ tone: "error", text: e instanceof Error ? e.message : "IPS could not be saved" });
        return false;
      } finally { setSaving(false); }
    };
    const next = saveChain.current.then(run, run);
    saveChain.current = next.then(() => undefined, () => undefined);
    return next;
  };

  saveRef.current = async () => { if (!(await saveIps())) throw new Error("save failed"); };

  /** Open the helper for the current highlight (icon, or the panel when `expanded`), or for no selection. */
  const openFromSelection = (expanded: boolean) => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && !sel.isCollapsed) {
      const r = sel.getRangeAt(0);
      const host = (r.commonAncestorContainer instanceof Element ? r.commonAncestorContainer : r.commonAncestorContainer.parentElement)?.closest<HTMLElement>("[data-ips-part]");
      if (host) { setPop({ id: ++seq.current, part: Number(host.dataset.ipsPart), range: r.cloneRange(), expanded }); return true; }
    }
    return false;
  };
  const onPointerKey = () => { if (!openFromSelection(false) && !pop?.expanded) setPop(null); };
  const askGeneral = () => { if (!openFromSelection(true)) setPop({ id: ++seq.current, part: null, range: null, expanded: true }); };

  const label: IpsStatusLabel = sendStatus?.status === "Returned by PM" || (sent && returnedLocal) ? "Returned by PM"
    : sendStatus?.status === "Sent to PM" || (!sendStatus && sent) ? "Sent to PM" : "Draft";
  const sentAtIso = sendStatus?.sentAt ?? sentRec?.sentAt ?? null;
  const sentLine = label === "Draft" ? "" : `${label === "Returned by PM" ? "Sent to PM" : label} · ${formatSentAt(sentAtIso)}`.replace(/ · $/, "");
  const noIps = sendStatus ? sendStatus.status === "No IPS" : !rec && !generated && savedVersion.current === undefined;
  const outdated = label !== "Draft" && !!sendStatus?.outdated && dismissedOutdated !== sendStatus.latestVersion;
  const emptiesNow = () => findEmptySections({ text, targetsCount: (storeExtras.targets ?? []).filter((t) => (t.text ?? "").trim() || t.amount).length, philosophy, risk, proportion, allocation });
  const openSend = () => setDlg({ kind: "send", empties: emptiesNow() });
  const doSend = async () => {
    setDlg((d) => d && { ...d, busy: true, error: undefined });
    try {
      if (!(await saveIps())) throw new IpsSendError("Not sent. The IPS is still a Draft.");
      const out = await arcApi.sendIpsToPm(clientId, savedVersion.current ?? null);
      sendIpsToPm(clientId, { buckets, demo, risk, philosophy, allocation, allocationNotes, signatures });  // local flag only after the backend accepted it
      await refreshSend();
      setDismissedOutdated(null);
      void out;
      setDlg(null);
    } catch (e) {
      setDlg((d) => d && { ...d, busy: false, error: e instanceof IpsSendError && e.message.startsWith("Generate") ? e.message : "Not sent. The IPS is still a Draft." });
    }
  };
  const doWithdraw = async () => {
    setDlg((d) => d && { ...d, busy: true, error: undefined });
    try { await arcApi.withdrawIpsSend(clientId); withdrawIpsFromPm(clientId); await refreshSend(); setDlg(null); }
    catch { setDlg((d) => d && { ...d, busy: false, error: "Not withdrawn. The IPS is still with the PM. Try again." }); }
  };

  return (
    <div data-ips-editor={clientId}>
      {!embedded && (<>
        <PageHeader eyebrow="Investment Policy Statement" title="Draft the IPS" subtitle={subtitle}
          actions={<GateChip id="G1" state={sent ? "pending" : "not_started"} />} />
        <Stepper steps={onboardingSteps} current={sent ? 3 : 2} />
      </>)}

      <div className="mx-auto mb-4 flex max-w-[1080px] flex-wrap items-center gap-4">
        <IpsStatusBadge status={label} detail={label === "Draft" ? undefined : formatSentAt(sentAtIso) || undefined} />
        {sendStatus?.sentVersion != null && label !== "Draft" && <span className="text-sm font-light text-ink-muted">PM has version {sendStatus.sentVersion}</span>}
      </div>
      {outdated && sendStatus && (
        <div role="status" className="mx-auto mb-4 flex max-w-[1080px] flex-wrap items-center justify-between gap-4 rounded-sm border border-hairline-strong bg-surface-200 px-6 py-4">
          <p className="text-[15px] font-light text-ink">The PM has an older version (v{sendStatus.sentVersion}). Send the updated version?</p>
          <div className="flex gap-3">
            <Button variant="secondary" onClick={() => setDismissedOutdated(sendStatus.latestVersion)}>Not now</Button>
            <Button onClick={openSend}>Send updated</Button>
          </div>
        </div>
      )}
      <div className="mx-auto mb-4 flex max-w-[1080px] items-center justify-between gap-4">
        <p className="text-xs text-ink-muted">Edit directly on the page. Highlight text to ask Geneva. Sections 2 and 4 are filled by the Portfolio Manager.</p>
        <div className="flex shrink-0 items-center">{previewBtn}</div>
      </div>

      <div onMouseUp={onPointerKey} onKeyUp={(e) => { if (e.key !== "Escape") onPointerKey(); }}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); askGeneral(); } }}
        className="mb-10">
        <IpsDocument version={version} clientName={client?.name ?? ""} clientId={clientId} mode="edit" edit={api} blank={blank} aiGenerated={!!generated} wide />
      </div>
      {pop && (
        <IpsEditPopover key={pop.id} clientId={clientId} target={pop}
          sections={RM_PARTS.map((n) => ({ part: n, title: parts.find((y) => y.part === n)?.title ?? `Part ${n}` }))}
          getText={(n) => text[n] ?? ""} onApplied={(n, v) => api.setText(n, v)} onClose={() => setPop(null)} />
      )}

      <p role="status" className="mx-auto mb-1 max-w-[1080px] text-right text-[12px] text-ink-muted">{autosave === "saving" ? "Saving…" : autosave === "saved" ? "Saved" : autosave === "error" ? "Not saved, press Save IPS" : ""}</p>
      {saveMsg && <p role={saveMsg.tone === "error" ? "alert" : "status"} className={`mx-auto mb-3 max-w-[1080px] text-right text-sm ${saveMsg.tone === "error" ? "text-red-700" : "text-ink"}`}>{saveMsg.text}</p>}
      <div className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-end gap-3">
        {noIps && !sent && <p role="status" className="mr-auto text-sm text-ink-muted">Generate an IPS first</p>}
        {sent && <p className="mr-auto text-sm font-light text-ink-500">{sentLine}. Withdraw to pull the draft back.</p>}
        {!embedded && !sent && <Button variant="secondary" onClick={() => nav(-1)}>Back</Button>}
        {sent && !embedded && <Button variant="secondary" to={`/rm/clients/${clientId}/ips-approval`}>Preview PM return</Button>}
        <Button variant="secondary" onClick={openPreview}><Eye size={16} className="mr-2" aria-hidden />Preview IPS document</Button>
        <Button variant="secondary" onClick={saveIps} disabled={saving}>{saving ? "Saving…" : "Save IPS"}</Button>
        {sent && <Button variant="secondary" onClick={() => setDlg({ kind: "withdraw", empties: [] })}>Withdraw</Button>}
        {!sent && <Button onClick={openSend} disabled={noIps}>Send IPS draft to PM</Button>}
      </div>
      {dlg?.kind === "send" && (
        <ConfirmDialog title="Send IPS draft to PM" busy={dlg.busy}
          primary={dlg.error ? "Retry" : dlg.empties.length ? "Send anyway" : "Send to PM"} secondary={dlg.error ? "Close" : dlg.empties.length ? "Go back" : "Cancel"}
          onPrimary={() => void doSend()} onSecondary={() => setDlg(null)}>
          {dlg.error ? <p role="alert" className="text-negative">{dlg.error}</p> : (<>
            <p>The Portfolio Manager will receive this IPS as version {savedVersion.current ?? "(new)"}. You can keep editing and withdraw it later.</p>
            {dlg.empties.length > 0 && (
              <div className="mt-4" role="alert">
                <p>These sections still show "Not yet completed":</p>
                <ul className="mt-2 list-disc pl-6">{dlg.empties.map((x) => <li key={x}>{x}</li>)}</ul>
              </div>
            )}
          </>)}
        </ConfirmDialog>
      )}
      {dlg?.kind === "withdraw" && (
        <ConfirmDialog title="Withdraw IPS from PM" busy={dlg.busy} primary={dlg.error ? "Retry" : "Withdraw"} secondary="Cancel" onPrimary={() => void doWithdraw()} onSecondary={() => setDlg(null)}>
          {dlg.error ? <p role="alert" className="text-negative">{dlg.error}</p> : <p>The IPS goes back to Draft and leaves the PM's inbox. Any PM return is cleared.</p>}
        </ConfirmDialog>
      )}
      {previewing && (
        <DocumentPreviewModal title="Preview IPS document" onClose={() => setPreviewing(false)}>
          <IpsDocument version={previewVersion} clientName={client?.name ?? ""} clientId={clientId} aiGenerated={!!generated} />
        </DocumentPreviewModal>
      )}
    </div>
  );
}
