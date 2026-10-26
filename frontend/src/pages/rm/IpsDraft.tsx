import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Button, GateChip, Loading, PageHeader, Stepper, useAsync } from "../../components/ui";
import { onboardingSteps } from "./rmShared";
import { getIpsDraftExtras, saveIpsDraftExtras, useIpsDraftExtras, sendIpsToPm, useIpsSent, withdrawIpsFromPm } from "../../services/workflowStore";
import { IpsDocument, type IpsEditApi } from "../../components/documents/IpsDocument";
import type { BucketId, SaaPortfolio } from "../../components/documents/ips/SaaPortfolios";
import type { Bucket3L, IpsVersion } from "../../types/arc";
import { IpsEditPopover, type PopoverTarget } from "../../components/geneva/IpsEditPopover";

const RM_PARTS = [1, 3, 5, 6];

export default function IpsDraft({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const nav = useNavigate();
  const parts = useAsync(() => arcApi.getIps(clientId), [clientId]);
  const [pop, setPop] = useState<(PopoverTarget & { id: number }) | null>(null);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const buckets0 = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const [text, setText] = useState<Record<number, string>>({});
  const [buckets, setBuckets] = useState<Bucket3L[]>([]);
  const [saaNotes, setSaaNotesState] = useState<Partial<Record<BucketId, string>>>({});
  const storeExtras = useIpsDraftExtras(clientId);
  const [demo, setDemo] = useState<Record<string, string>>({});
  const [risk, setRisk] = useState<Record<string, string>>({});
  const [signatures, setSignatures] = useState<{ client?: string; rm?: string }>({});
  const [saaPortfolios, setSaaPortfolios] = useState<Partial<Record<BucketId, SaaPortfolio>>>({});
  const hydrated = useRef(false);
  const sent = !!useIpsSent(clientId);
  const seq = useRef(0);
  useEffect(() => {
    if (parts) setText(Object.fromEntries(parts.map((p) => [p.part, p.body])));
  }, [parts]);
  useEffect(() => {
    if (!buckets0 || hydrated.current) return;
    const x = getIpsDraftExtras(clientId);
    setBuckets(x.buckets ?? buckets0); setSaaNotesState(x.saaNotes ?? {});
    setDemo(x.demo ?? {}); setRisk(x.risk ?? {}); setSignatures(x.signatures ?? {}); setSaaPortfolios(x.saaPortfolios ?? {});
    hydrated.current = true;
  }, [buckets0, clientId]);
  useEffect(() => { if (hydrated.current && buckets.length) saveIpsDraftExtras(clientId, { buckets, saaNotes, demo, risk, signatures, saaPortfolios }); }, [buckets, saaNotes, demo, risk, signatures, saaPortfolios, clientId]);
  /** Store is the source of truth for notes/portfolios: pull in changes made outside this page (Geneva chat). */
  useEffect(() => {
    if (!hydrated.current) return;
    const n = storeExtras.saaNotes ?? {}, p = storeExtras.saaPortfolios ?? {};
    setSaaNotesState((c) => JSON.stringify(c) === JSON.stringify(n) ? c : n);
    setSaaPortfolios((c) => JSON.stringify(c) === JSON.stringify(p) ? c : p);
  }, [storeExtras.saaNotes, storeExtras.saaPortfolios]);
  const version = useMemo<IpsVersion | null>(() => parts ? {
    version: 0, issuedOn: new Date().toISOString(), status: "Draft", author: "Relationship Manager", summary: "Onboarding draft", parts,
  } : null, [parts]);
  if (!parts || !version || !buckets0 || !hydrated.current) return <Loading />;
  const api: IpsEditApi = { text, setText: (n, v) => setText((t) => ({ ...t, [n]: v })), buckets, setBuckets, saaNotes, setSaaNotes: (id, v) => setSaaNotesState((m) => ({ ...m, [id]: v })),
    demo, setDemo: (l, v) => setDemo((d) => ({ ...d, [l]: v })),
    risk, setRisk: (l, v) => setRisk((d) => ({ ...d, [l]: v })),
    signatures, setSignature: (who, url) => setSignatures((g) => ({ ...g, [who]: url })),
    saaPortfolios, setSaaPortfolio: (id, p) => setSaaPortfolios((m) => ({ ...m, [id]: p })),
  };
  const subtitle = `You fill ${RM_PARTS.map((n) => parts.find((x) => x.part === n)?.title ?? "").filter(Boolean).join(", ")}.`;

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

  return (
    <div>
      {!embedded && (<>
        <PageHeader eyebrow="Investment Policy Statement" title="Draft the IPS" subtitle={subtitle}
          actions={<GateChip id="G1" state={sent ? "pending" : "not_started"} />} />
        <Stepper steps={onboardingSteps} current={sent ? 3 : 2} />
      </>)}

      <div className="mx-auto mb-4 flex max-w-[780px] items-center justify-between gap-4">
        <p className="text-xs text-ink-muted">Edit directly on the page. Highlight text to ask Geneva. Sections 2 and 4 are filled by the Investment Counsellor.</p>
        <button type="button" data-ips-ask aria-label="Ask Geneva" title="Ask Geneva (Ctrl/Cmd+K)" onClick={askGeneral}
          className="flex shrink-0 cursor-pointer items-center rounded-sm border border-hairline-strong bg-surface-100 p-2 hover:bg-surface-300">
          <img src="/ubs-logo.png" alt="" className="ubs-logo h-5 w-auto" />
        </button>
      </div>

      <div onMouseUp={onPointerKey} onKeyUp={(e) => { if (e.key !== "Escape") onPointerKey(); }}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); askGeneral(); } }}
        className="mb-10">
        <IpsDocument version={version} clientName={client?.name ?? ""} clientId={clientId} mode="edit" edit={api} />
      </div>
      {pop && (
        <IpsEditPopover key={pop.id} clientId={clientId} target={pop}
          sections={RM_PARTS.map((n) => ({ part: n, title: parts.find((y) => y.part === n)?.title ?? `Part ${n}` }))}
          getText={(n) => text[n] ?? ""} onApplied={(n, v) => api.setText(n, v)} onClose={() => setPop(null)} />
      )}

      <div className="mx-auto flex max-w-[780px] flex-wrap items-center justify-end gap-3">
        {sent ? (<>
          <p className="mr-auto text-sm text-ink-500">Sent to the Investment Counsellor. Withdraw to pull the draft back.</p>
          {!embedded && <Button variant="secondary" to={`/rm/clients/${clientId}/ips-approval`}>Preview PM return</Button>}
          <Button onClick={() => withdrawIpsFromPm(clientId)}>Withdraw</Button>
        </>) : (<>
          {!embedded && <Button variant="secondary" onClick={() => nav(-1)}>Back</Button>}
          <Button onClick={() => sendIpsToPm(clientId, { buckets, saaNotes, demo, risk, signatures, saaPortfolios })}>Send to Investment Counsellor</Button>
        </>)}
      </div>
    </div>
  );
}
