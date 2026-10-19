import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, ChevronDown, Lock } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button } from "../../components/ui";
import { ProfileCarousel, ProfileEdit, SectionBlocksView, SectionBody, WordingCompare, composeProfile, parseProfile, parseSaaLines, useSeededBlocks, withText, primaryText, isSources, isHiddenFor, PendingBox, type usePackStatus } from "./rmShared";
import { hasHeadings, parseBlocks, composeBlocks } from "../../services/packBlocks";
import { BlockEditor, saveSectionBlocks } from "../../components/documents/pack";
import { setSectionDone } from "../../services/packDraftStore";
import { ProfessionaliseButton } from "../../components/geneva/ProfessionaliseButton";
import { getChatContext } from "../../services/chatContextStore";
import { ROLE_LABEL, type AllocationRow, type PackSection, type Role } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";

/** One section of the review pack, rendered in place inside the document: read view, inline editor, Professionalise at the bottom right. */
export function PackSectionPanel({ clientId, s, pos, role, onboarding, approved, status, alloc, extra, updatedNote, open, onToggle }: {
  clientId: string; s: PackSection; pos: number; role: Role; onboarding: boolean; approved: boolean;
  status: ReturnType<typeof usePackStatus>; alloc?: AllocationRow[];
  /** Special body for sign-off and sources sections; receives the editing flag. */
  extra?: (editing: boolean) => ReactNode; updatedNote?: string;
  /** Expanded state is owned by the document so Expand all / Collapse all can drive every section. */
  open: boolean; onToggle: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [compare, setCompare] = useState<{ oldText: string; newText: string } | null>(null);
  const [saaDraft, setSaaDraft] = useState<number[] | null>(null);
  const [proposed, setProposed] = useState(false);
  const [polishErr, setPolishErr] = useState("");
  const blocks = useSeededBlocks(clientId, s.n, s.body ?? "", s.chart, onboarding && s.chart === "saa");
  const textNow = primaryText(blocks);
  const sources = isSources(s);
  const signoff = s.kind === "signoff";
  const hidden = isHiddenFor(s, role, status.complete) && !sources;
  const mine = s.owner === role;
  const canEdit = mine && !signoff && !sources && !approved;
  const canPolish = mine && !signoff && !sources && !hidden;
  const canMark = mine && !signoff && !hidden;
  const rmOwned = (mine && !signoff) || signoff;
  const readOnly = !mine && !signoff && !sources && !hidden;
  /** Every section collapses on click; the viewer's own sections start open, the rest collapsed (default set by the document). */
  const shown = open;
  const isDone = !!status.done[s.n]?.done;

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
      const items = parts.flatMap((b, k) => (skip(b.heading) ? [] : [{ id: String(k), label: `${pos}. ${s.title}${b.heading ? ` (${b.heading})` : ""}`, text: b.text }]));
      const out = await arcApi.professionalise({ clientId, role, context: "pack", items, chat: getChatContext(clientId, role) });
      const byId = Object.fromEntries(out.map((o) => [o.id, o.text]));
      const merged = parts.map((b, k) => [b.heading ?? "", byId[String(k)] ?? b.text] as [string, string]);
      setCompare({ oldText: textNow, newText: hasHeadings(textNow) ? composeBlocks(merged) : merged[0][1] });
    } catch {
      setPolishErr("Could not generate wording. Try again.");
    } finally {
      setBusy(false);
    }
  };
  const acceptPolish = () => {
    if (!compare) return;
    saveSectionBlocks(clientId, s.n, withText(blocks, compare.newText), role);
    setCompare(null);
  };

  return (
    <section className={rmOwned ? "border-l-2 border-brand pl-4 sm:pl-6" : ""}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 cursor-pointer" role="button" tabIndex={0} aria-expanded={open} onClick={onToggle} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}>
          <h2 className="flex items-baseline gap-5 text-[28px] font-light leading-9 [overflow-wrap:anywhere]">
            <span className="w-9 shrink-0 text-[18px] text-ink-muted">{pos}</span>{s.title}
            <ChevronDown size={20} className={`shrink-0 self-center text-ink-muted transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </h2>
          <p className="mt-2 pl-14 text-xs text-ink-muted">
            {ROLE_LABEL[s.owner]} ({ROLE_PEOPLE[s.owner].person})
            {rmOwned && <span className="ml-3 uppercase tracking-[0.14em] text-brand">You fill in this section</span>}
            {readOnly && <span className="ml-3 inline-flex items-center gap-1 uppercase tracking-[0.14em]"><Lock size={11} />Read only</span>}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {shown && s.owner === "ic" && role !== "ic" && <Badge tone="green">IC reviewed thoroughly</Badge>}
          {canMark && (isDone ? (
            <span className="flex items-center gap-3 text-sm text-ink-muted"><span className="flex items-center gap-1.5"><Check size={14} />Done</span>
              <Button variant="secondary" size="sm" onClick={() => setSectionDone(clientId, s.n, false, role)}>Reopen</Button></span>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setSectionDone(clientId, s.n, true, role)}><Check size={14} />Mark as done</Button>
          ))}
        </div>
      </div>

      {shown && <>
      <div className="mt-6 space-y-6 text-[16px] font-light leading-8 text-ink-700 ">
        {!hidden && updatedNote && <p className="text-xs text-ink-muted">{updatedNote}</p>}
        {s.status === "flagged" && !hidden && (
          <div className="flex items-start gap-3 rounded-md bg-surface-300 p-5 text-sm text-ink"><AlertTriangle size={18} className="mt-0.5 shrink-0" />Flagged line: please read this section closely before approving.</div>
        )}
        {hidden ? (
          <PendingBox owner={s.owner} />
        ) : compare ? (
          <WordingCompare oldText={compare.oldText} newText={compare.newText} onChangeNew={(t) => setCompare({ ...compare, newText: t })} onAccept={acceptPolish} onKeep={() => setCompare(null)} />
        ) : editing && canEdit ? (
          s.n === 1 ? <ProfileEdit key={clientId} clientId={clientId} blocks={blocks} onChange={(b) => saveSectionBlocks(clientId, 1, b, role)} saa={showSaa ? { rows: saaRows, vals: saaVals, setVals: setSaaDraft } : undefined} />
            : <BlockEditor clientId={clientId} section={s.n} blocks={blocks} onChange={(b) => saveSectionBlocks(clientId, s.n, b, role)} />
        ) : s.n === 1 ? (
          <ProfileCarousel clientId={clientId} blocks={blocks} saa={showSaa ? { rows: saaRows, vals: saaVals, setVals: setSaaDraft } : undefined} />
        ) : sources ? extra?.(editing)
          : extra ? <SectionBody n={s.n} text={textNow} extra={extra(editing)} />
          : <SectionBlocksView blocks={blocks} clientId={clientId} />}
      </div>

      {!hidden && !compare && (canEdit || canPolish || (sources && !approved)) && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
          <div>{(canEdit || sources) && <Button variant="secondary" size="sm" onClick={() => setEditing(!editing)}>{editing ? "Done" : sources ? "Edit sources" : "Edit section"}</Button>}</div>
          <div className="flex flex-wrap items-center justify-end gap-4">
            {polishErr && <span className="text-xs text-negative" role="alert">{polishErr}</span>}
            {showSaa && canPolish ? (
              <>
                {proposed && <span className="text-xs text-ink-muted" role="status">Proposed SAA saved</span>}
                <Button disabled={saaTotal !== 100} onClick={proposeSaa}>Propose SAA</Button>
              </>
            ) : canPolish && <ProfessionaliseButton onClick={runPolish} loading={busy} label="Professionalise" />}
          </div>
        </div>
      )}
      </>}
    </section>
  );
}
