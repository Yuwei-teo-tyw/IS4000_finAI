import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Check, Lock, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { BulletTextarea, Button, GateChip, Loading, NextAction, PageHeader, Section, toBulletItems, useAsync } from "../../components/ui";
import { SavedStatus, useAutoSave } from "../../components/ic/SavedStatus";
import { ipsKey, sendIpsIcToRm, useIpsIcHandover, useIpsRequest } from "../../services/workflowStore";
import { loadPackDrafts, savePackDraft, setSectionDone, useSectionDone } from "../../services/packDraftStore";
import { SaaPanel, SectionBlocksView, parseSaaLines, useSeededBlocks } from "../rm/rmShared";
import { BackLink } from "./icHelpers";

const SAA_SECTION = 2, BUCKET_SECTION = 4;
const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
const r1 = (n: number) => Math.round(n * 10) / 10;

/** Read-only view of a section the RM wrote (content comes from the IPS pack stores under ipsKey). */
function RmSectionBody({ id, n, body }: { id: string; n: number; body: string }) {
  const blocks = useSeededBlocks(id, n, body, undefined, true);
  const has = blocks.some((b) => b.type !== "text" || b.text.trim());
  return has ? <SectionBlocksView blocks={blocks} clientId={id} /> : <p className="text-sm text-ink-muted">Nothing recorded.</p>;
}

export default function IcIpsSaa() {
  const { clientId = "jfr" } = useParams();
  const id = ipsKey(clientId);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const sections = useAsync(() => arcApi.getIpsSections(clientId), [clientId]);
  const alloc = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const request = useIpsRequest(clientId);
  const handover = useIpsIcHandover(clientId);
  const done = useSectionDone(id);
  const [vals, setVals] = useState<number[]>([]);
  const [why, setWhy] = useState("");
  const [buckets, setBuckets] = useState("");
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<string | undefined>();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!alloc || !sections) return;
    const d = loadPackDrafts(id);
    const saaText = d[SAA_SECTION] ?? "";
    const parsed = parseSaaLines(saaText);
    setVals(alloc.map((r) => parsed[r.assetClass] ?? r.saa));
    setWhy(toBulletItems(saaText).filter((l) => !alloc.some((r) => l.startsWith(`${r.assetClass}:`) && /\d\s*%/.test(l))).map((l) => `• ${l}`).join("\n"));
    setBuckets(d[BUCKET_SECTION] ?? sections.find((x) => x.n === BUCKET_SECTION)?.body ?? "");
    setDirty(false); setReady(true);
  }, [alloc, sections, id]);

  const composeSaa = () => [...(alloc ?? []).map((r, i) => `• ${r.assetClass}: ${vals[i] ?? 0}%`), ...(why.trim() ? [why.trim()] : [])].join("\n");
  const saveNow = () => {
    savePackDraft(id, SAA_SECTION, composeSaa(), "ic");
    savePackDraft(id, BUCKET_SECTION, buckets, "ic");
    setDirty(false); setSavedAt(new Date().toISOString());
  };
  useAutoSave(saveNow, dirty && ready, [vals, why, buckets]);

  if (!client || !sections || !alloc) return <Loading />;
  const edit = <T,>(set: (v: T) => void) => (v: T) => { set(v); setDirty(true); };
  const total = r1(vals.reduce((a, b) => a + b, 0));
  const totalOk = total === 100;
  const mark = (n: number, v: boolean) => { if (v) saveNow(); setSectionDone(id, n, v, "ic"); };
  const rmSections = sections.filter((x) => x.owner === "rm");
  const icReady = !!done[SAA_SECTION]?.done && !!done[BUCKET_SECTION]?.done && totalOk;
  const doneToggle = (n: number, ok = true) => (done[n]?.done ? (
    <span className="flex items-center gap-3 text-sm text-ink-muted"><span className="flex items-center gap-1.5"><Check size={14} />Done</span>
      <Button variant="secondary" size="sm" onClick={() => mark(n, false)}>Reopen</Button></span>
  ) : <Button variant="secondary" size="sm" disabled={!ok} onClick={() => mark(n, true)}><Check size={14} />Mark as done</Button>);

  if (!request) {
    return (
      <div>
        <BackLink to="/ic/inbox">Back to inbox</BackLink>
        <PageHeader eyebrow={`${client.name} · IPS`} title="Propose the strategic asset allocation" subtitle="The Relationship Manager has not handed over an IPS for this client yet." />
      </div>
    );
  }

  return (
    <div>
      <SavedStatus dirty={dirty} savedAt={savedAt} />
      <BackLink to="/ic/inbox">Back to inbox</BackLink>
      <PageHeader eyebrow={`${client.name} · IPS`} title="Propose the strategic asset allocation" subtitle={`Handed over by the Relationship Manager on ${fmt(request.sentAt)}.`} actions={<GateChip id="G2" state={handover ? "pending" : "not_started"} />} />

      <Section title="From the Relationship Manager" hint="Read only. A tick means the RM marked the section done.">
        <div className="flex flex-col gap-3">
          {rmSections.map((x) => {
            const ok = !!done[x.n]?.done;
            return (
              <details key={x.n} className="border border-hairline bg-surface-100">
                <summary className="flex cursor-pointer items-center justify-between gap-4 px-6 py-4 text-[15px] text-ink">
                  <span className="flex items-center gap-2"><Lock size={12} className="text-ink-muted" aria-hidden />{x.n}. {x.title}</span>
                  {ok ? <Check size={16} className="text-positive" aria-label="Done" /> : <X size={16} className="text-negative" aria-label="Not done" />}
                </summary>
                <div className="border-t border-hairline px-6 py-6 text-[15px] leading-7 text-ink-700"><RmSectionBody id={id} n={x.n} body={x.body} /></div>
              </details>
            );
          })}
        </div>
      </Section>

      <div className="mt-16" />
      <Section title={`${SAA_SECTION}. ${sections.find((x) => x.n === SAA_SECTION)?.title ?? "Strategic asset allocation proposal"}`}>
        <div className="mb-6 flex justify-end">{doneToggle(SAA_SECTION, totalOk)}</div>
        <SaaPanel saa={{ rows: alloc, vals, setVals: edit(setVals) }} />
        <label htmlFor="saa-why" className="mb-2 mt-10 block text-base font-light text-ink">Rationale</label>
        <BulletTextarea id="saa-why" rows={5} value={why} onChange={edit(setWhy)} />
      </Section>

      <div className="mt-16" />
      <Section title={`${BUCKET_SECTION}. ${sections.find((x) => x.n === BUCKET_SECTION)?.title ?? "3L buckets and explanation"}`}>
        <div className="mb-6 flex justify-end">{doneToggle(BUCKET_SECTION)}</div>
        <BulletTextarea id="ips-3l" rows={7} value={buckets} onChange={edit(setBuckets)} />
      </Section>

      <div className="mt-16">
        <NextAction title="Send to Relationship Manager"
          body={handover ? `Handed over to the RM on ${fmt(handover.sentAt)}.${icReady ? " Send again to share later edits." : ""}` : icReady ? "Sections 2 and 4 are done." : "Mark sections 2 and 4 as done to send."}
          action={<Button disabled={!icReady} onClick={() => { saveNow(); sendIpsIcToRm(clientId); }}>Send to Relationship Manager</Button>} />
      </div>
    </div>
  );
}
