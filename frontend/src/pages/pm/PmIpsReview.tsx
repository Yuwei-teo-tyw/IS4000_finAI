import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Eye } from "lucide-react";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { buildIpsData } from "../../components/documents/ips/ipsData";
import { arcApi } from "../../services/arcApi";
import { Button, GateChip, Loading, PageHeader, useAsync } from "../../components/ui";
import { IpsDocument, type IpsEditApi } from "../../components/documents/IpsDocument";
import { seedFromData } from "../../components/documents/ips/ipsData";
import { type AllocWeights, type ThreeLMeta } from "../../components/documents/ips/Allocation";
import { getIpsDraftExtras, saveIpsDraftExtras, returnIpsToRm, useIpsReturned, type IpsDraftExtras } from "../../services/workflowStore";
import { returnPmIpsToRm } from "../../services/ipsHandover";
import { PmSaaBucket, type SaaStatus } from "../../components/documents/ips/PmSaaBucket";
import type { Bucket3L, IpsVersion, ThreeLProportion } from "../../types/arc";
import type { PmModelSaa, SaaBucketId } from "../../types/modelSaa";
import type { PmIps } from "../../services/arcApi";
import { BackLink, Msg } from "./pmHelpers";

const PM_SIGNATURE_URL = "/signatures/pm-weilun.png";
const SAA_BUCKETS: SaaBucketId[] = ["longevity", "legacy"];
const LABEL: Record<SaaBucketId, string> = { longevity: "Longevity", legacy: "Legacy" };
const AUTOSAVE_MS = 1000;

/** The model SAA the backend holds for a bucket (saved by an earlier visit), if the PM chose a library model. */
function savedModel(pm: PmIps | null | undefined, b: SaaBucketId): PmModelSaa | undefined {
  const s = pm?.saa?.[b];
  if (!s || s.source !== "pm" || !s.modelId || !s.weights) return undefined;
  return { modelId: s.modelId, modelName: s.modelName ?? s.modelId, strategy: s.strategy ?? "", modelWeights: s.modelWeights ?? s.weights,
    recommendedModelId: s.recommendedModelId ?? null, recommendedWeights: s.recommendedWeights ?? null, recommendationId: s.recommendationId ?? null,
    weights: s.weights, overrideReason: s.overrideReason ?? "" };
}
const saaPayload = (m: PmModelSaa) => ({ modelId: m.modelId, weights: m.weights, recommendedModelId: m.recommendedModelId,
  recommendedWeights: m.recommendedWeights, recommendationId: m.recommendationId, ...(m.overrideReason.trim() ? { overrideReason: m.overrideReason.trim() } : {}) });

/** The PM's one page for an IPS SAA request: the RM's sent IPS, with section 5 (3L and SAA) highlighted and editable, the rest read-only. */
export default function PmIpsReview() {
  const { clientId = "" } = useParams();
  const navigate = useNavigate();
  const returned = useIpsReturned(clientId);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const buckets0 = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const src = useAsync(async () => {
    const pm = await arcApi.getPmIps(clientId).catch(() => null);  // the version the RM sent
    const rec = await arcApi.getIpsVersionRecord(clientId, pm?.snapshotVersion || undefined);
    return { rec, parts: rec ? rec.parts : await arcApi.getIps(clientId), pm };
  }, [clientId]);
  const seed = useMemo(() => (src?.rec?.data ? seedFromData(src.rec.data) : null), [src]);
  const [ready, setReady] = useState(false);
  const [buckets, setBuckets] = useState<Bucket3L[]>([]);
  const [proportion, setProportion] = useState<ThreeLProportion | null>(null);
  const [allocation, setAllocation] = useState<{ liquidity?: string; longevity?: string; legacy?: string }>({});
  const [weights, setWeights] = useState<AllocWeights>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<Partial<Record<"liquidity" | "longevity" | "legacy", ThreeLMeta>>>({});
  const [pmSig, setPmSig] = useState<{ image?: string; signedAt?: string }>({});
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [modelSaa, setModelSaa] = useState<Partial<Record<SaaBucketId, PmModelSaa>>>({});
  const [saaStatus, setSaaStatus] = useState<Partial<Record<SaaBucketId, SaaStatus>>>({});
  const [saved, setSaved] = useState<{ at?: string; error?: string }>({});
  const lastSaved = useRef<Partial<Record<SaaBucketId, string>>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!buckets0 || !src || ready) return;
    const x = getIpsDraftExtras(clientId);
    setBuckets(buckets0);
    setProportion(seed?.proportion ?? null);
    setAllocation((({ liquidity: _l, ...r }) => r)(seed?.allocation ?? x.allocation ?? {}));
    setNotes((({ liquidity: _l, ...r }) => r)(seed?.allocationNotes ?? x.allocationNotes ?? {}));
    setMeta(seed?.allocationMeta ?? {});
    const wm: AllocWeights = { ...(x.allocationWeights ?? {}) };
    SAA_BUCKETS.forEach((b) => { const s = src.pm?.saa?.[b]; if (!wm[b] && s?.source === "pm" && s.strategy && s.weights) wm[b] = { strategy: s.strategy, weights: s.weights }; });
    setWeights(wm);
    // Model SAA: this tab's draft first (it may hold edits that do not pass the checks yet), else what the backend saved.
    const ms: Partial<Record<SaaBucketId, PmModelSaa>> = {};
    SAA_BUCKETS.forEach((b) => {
      const back = savedModel(src.pm, b);
      if (back) lastSaved.current[b] = JSON.stringify(saaPayload(back));
      const m = x.modelSaa?.[b] ?? back;
      if (m) ms[b] = m;
    });
    setModelSaa(ms);
    const sg = x.signatures as { pm?: string; pmSignedAt?: string } | undefined;
    if (sg?.pm) { setPmSig({ image: sg.pm, signedAt: sg.pmSignedAt }); setReady(true); return; }
    // No saved PM signature: default to the bundled one (as a data URL, like an uploaded one) dated today.
    setReady(true);
    fetch(PM_SIGNATURE_URL).then((r) => r.blob()).then((b) => new Promise<string>((res, rej) => { const f = new FileReader(); f.onload = () => res(String(f.result)); f.onerror = rej; f.readAsDataURL(b); }))
      .then((image) => setPmSig((cur) => cur.image ? cur : { image, signedAt: new Date().toISOString() })).catch(() => {});
  }, [buckets0, src, seed, ready, clientId]);
  // Geneva's sidebar chat reads the open IPS from the shared draft extras.
  // The PM signature rides in the draft extras' signatures so the RM sees it after the return.
  useEffect(() => {
    if (!ready) return;
    const prev = getIpsDraftExtras(clientId).signatures ?? {};
    const signatures = { ...prev, pm: pmSig.image, pmSignedAt: pmSig.image ? pmSig.signedAt : undefined } as IpsDraftExtras["signatures"];
    saveIpsDraftExtras(clientId, { buckets, allocation, allocationNotes: notes, allocationWeights: weights, signatures, pmOpened: true, modelSaa });
  }, [ready, buckets, allocation, notes, weights, pmSig, clientId, modelSaa]);
  // Autosave each bucket's model SAA to the backend once it passes its checks, so the PM can leave and come back.
  useEffect(() => {
    if (!ready || returned) return;
    const due = SAA_BUCKETS.filter((b) => modelSaa[b] && saaStatus[b]?.ready && lastSaved.current[b] !== JSON.stringify(saaPayload(modelSaa[b]!)));
    if (!due.length) return;
    const t = setTimeout(() => {
      const payload = Object.fromEntries(due.map((b) => [b, saaPayload(modelSaa[b]!)]));
      arcApi.savePmIps(clientId, { saa: payload })
        .then(() => { due.forEach((b) => { lastSaved.current[b] = JSON.stringify(payload[b]); }); setSaved({ at: new Date().toISOString() }); })
        .catch((e) => setSaved({ error: e instanceof Error ? e.message : String(e) }));
    }, AUTOSAVE_MS);
    return () => clearTimeout(t);
  }, [ready, returned, modelSaa, saaStatus, clientId]);

  // Local check: each bucket's model SAA passes its checks (PmSaaBucket) and the 3L split sums to 100%.
  // Same source as the displayed Total (section 5 sums the editable buckets, one per id so nothing is counted twice); the proportion only supplies reasons.
  const splitTotal = buckets.length ? Math.round(Array.from(new Map(buckets.map((b) => [b.id, b.pct])).values()).reduce((s, n) => s + n, 0) * 100) / 100 : null;
  const problems = [
    ...SAA_BUCKETS.flatMap((b) => saaStatus[b]?.problems ?? [`Loading the ${LABEL[b]} recommendation…`]),
    ...(splitTotal === null ? ["The 3L split is not available."] : splitTotal !== 100 ? [`The 3L split adds to ${splitTotal}%, not 100%.`] : []),
  ];
  const passed = problems.length === 0;

  if (!src || !client || !ready || !src.parts) return <Loading />;
  const { rec, parts, pm } = src;
  const version: IpsVersion = { version: rec?.version ?? pm?.snapshotVersion ?? 0, issuedOn: rec?.issuedOn ?? new Date().toISOString(), status: "Draft", author: "Relationship Manager", summary: "Sent by the RM", parts };
  const text: Record<number, string> = Object.fromEntries(parts.map((p) => [p.part, p.body]));
  Object.assign(text, seed?.text ?? {});
  const api: IpsEditApi = {
    saaFor: (b) => (
      <PmSaaBucket key={b} clientId={clientId} bucket={b} value={modelSaa[b]} editable
        onChange={(m) => { setModelSaa((cur) => (m ? { ...cur, [b]: m } : Object.fromEntries(Object.entries(cur).filter(([k]) => k !== b)))); if (m) setAllocation((a) => ({ ...a, [b]: m.strategy })); }}
        onStatus={(s) => setSaaStatus((cur) => ({ ...cur, [b]: s }))} />
    ),
    modelSaa: Object.fromEntries(SAA_BUCKETS.filter((b) => modelSaa[b]).map((b) => [b, { modelId: modelSaa[b]!.modelId, modelName: modelSaa[b]!.modelName, weights: modelSaa[b]!.weights,
      recommendedModelId: modelSaa[b]!.recommendedModelId, overrideReason: modelSaa[b]!.overrideReason }])),
    totalWealth: pm?.total ?? null,
    text, setText: () => {}, buckets, setBuckets, demo: seed?.demo ?? {}, setDemo: () => {}, risk: seed?.risk ?? {}, setRisk: () => {},
    philosophy: seed?.philosophy ?? {}, setPhilosophy: () => {}, signatures: getIpsDraftExtras(clientId).signatures ?? {}, setSignature: () => {},
    allocation, allocationNotes: notes, allocationWeights: weights,
    setAllocationWeights: (b, w) => setWeights((m) => { if (b === "liquidity") return m; const { [b]: _o, ...r } = m; return w ? { ...r, [b]: { strategy: allocation[b] ?? "", weights: w } } : r; }),
    proposedAllocation: seed?.proposed, allocationMeta: meta, proportion, proportionMessage: seed?.proportionMessage, outOfDate: seed?.outOfDate,
    setProportionPct: (k, n) => setProportion((p) => p ? { ...p, [k]: { ...p[k], pct: Number.isFinite(n) ? Math.max(0, n) : 0 } } : p),
    setProportionReason: (k, t) => setProportion((p) => p ? { ...p, [k]: { ...p[k], reason: t } } : p),
    setAllocationNote: (b, t) => setNotes((n) => ({ ...n, [b]: t })),
    setAllocation: (b, c) => { if (b !== "liquidity") setWeights((m) => { const { [b]: _o, ...r } = m; return r; }); setAllocation((a) => ({ ...a, [b]: b === "liquidity" ? "NA" : c })); },
  };

  /** Preview renders the IPS read-only from the live page state, so unsaved PM edits show too. */
  const previewVersion: IpsVersion = previewing
    ? { ...version, data: buildIpsData(rec?.data, { text, demo: seed?.demo ?? {}, risk: seed?.risk ?? {}, philosophy: seed?.philosophy ?? {}, allocation, allocationNotes: notes, allocationMeta: meta, notIncluded: [], proportion }) }
    : version;
  const fail = (e: unknown) => setMsg({ ok: false, text: e instanceof Error ? e.message : "Something went wrong." });
  const save = async () => {
    const pctOf = (id: Bucket3L["id"]) => buckets.find((b) => b.id === id)?.pct ?? proportion?.[id].pct ?? 0;
    const pct = buckets.length || proportion ? { liquidity: pctOf("liquidity"), longevity: pctOf("longevity"), legacy: pctOf("legacy") } : null;
    await arcApi.savePmIps(clientId, {
      ...(pct ? { threeL: { liquidity: { pct: pct.liquidity }, longevity: { pct: pct.longevity }, legacy: { pct: pct.legacy } } } : {}),
      saa: Object.fromEntries(SAA_BUCKETS.filter((b) => modelSaa[b]).map((b) => [b, saaPayload(modelSaa[b]!)])),
    });
  };
  const send = async () => {
    setBusy(true); setMsg(null);
    try { await save(); await returnPmIpsToRm(clientId); returnIpsToRm(clientId); navigate("/pm/inbox"); }
    catch (e) { fail(e); setBusy(false); }
  };
  const signed = !!pmSig.image;

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · IPS SAA request`} title="Review the IPS"
        subtitle="The IPS the RM sent. Vet and edit the highlighted 3L and SAA section; the other sections are read-only."
        actions={<GateChip id="G2" state={returned ? "pending" : "not_started"} />} />
      {returned
        ? <div className="mx-auto mb-4 max-w-[1480px]"><Msg ok>Sent back to the RM. Awaiting RM approval.</Msg></div>
        : <p className="mx-auto mb-4 max-w-[1480px] text-xs text-ink-muted">In section 5, review the Portfolio Agent's recommended model SAA for Longevity and Legacy, accept it or choose another, and amend the weights. Ask Geneva in the sidebar about this IPS.</p>}
      <div className="mb-10">
        <IpsDocument version={version} clientName={client.name} clientId={clientId} mode={returned ? "view" : "edit"} edit={returned ? undefined : api} wide pmReview={!returned}
          pmSign={returned ? undefined : { image: pmSig.image, signedAt: pmSig.signedAt, onChange: (d) => setPmSig(d ? { image: d, signedAt: new Date().toISOString() } : {}) }}  />
      </div>

      <div className="mx-auto mb-6 flex max-w-[1480px]">
        <Button variant="secondary" onClick={() => setPreviewing(true)}><Eye size={16} className="mr-2" aria-hidden />Preview IPS document</Button>
      </div>
      {previewing && (
        <DocumentPreviewModal title="Preview IPS document" onClose={() => setPreviewing(false)}>
          <IpsDocument version={previewVersion} clientName={client.name} clientId={clientId} mode="view" edit={api} pmSign={{ image: pmSig.image, signedAt: pmSig.signedAt }} />
        </DocumentPreviewModal>
      )}

      {!returned && (
        <section className="mx-auto mb-12 max-w-[1480px] border-t border-hairline pt-8" aria-label="Combined check and send back">
          <h2 className="text-xl font-light">Check and send back to the RM</h2>
          <p className="mt-6 text-sm" aria-live="polite" data-testid="local-check">{passed ? "" : `Check failed. ${problems.join(" ")}`}</p>
          {msg && <div className="mt-6"><Msg ok={msg.ok}>{msg.text}</Msg></div>}
          <p className="mt-4 text-xs text-ink-muted" aria-live="polite">{saved.error ? `Not saved to the database: ${saved.error}` : saved.at ? `Model SAAs saved to the database at ${new Date(saved.at).toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit" })}.` : "Each model SAA is saved to the database once it passes its checks."}</p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button variant="gold" disabled={busy || !passed || !signed} onClick={send}>Send back to RM</Button>
            {passed && !signed && <span className="text-sm text-ink-muted">Add the Portfolio Manager signature to send.</span>}
          </div>
        </section>
      )}
      <BackLink to="/pm/inbox">Back to inbox</BackLink>
    </div>
  );
}
