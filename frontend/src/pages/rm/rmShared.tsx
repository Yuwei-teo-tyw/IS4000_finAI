import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Lock, X } from "lucide-react";
import { CitationTag, BulletList, Badge, Button, SCRIPT_FONT, SignatureBlock, toBulletItems } from "../../components/ui";
import type { DocSection } from "../../components/export/CompiledDocument";
import { parseBlocks, hasHeadings, composeBlocks } from "../../services/packBlocks";
import { ROLE_LABEL, type AllocationRow, type IpsPart, type PackBlock, type PackSection, type Role } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { BlockEditor, BlockItem, newBlockId, useSectionBlocks } from "../../components/documents/pack";
import { SaaDonut } from "../../components/documents/ips/charts";
import { loadPackDrafts, loadRawBlocks, loadSignatures, savePackDraft, subscribePackDrafts, subscribeSignatures, useSectionDone, type PackSignatures as Sigs } from "../../services/packDraftStore";
import { useAllFinalised, useIcHandover, useReviewRequest } from "../../services/workflowStore";
import { arcApi } from "../../services/arcApi";
import { useAsync } from "../../components/ui";

/** Render text, turning [TAG-123] markers into citation chips. */
export function Tagged({ text }: { text: string }) {
  const parts = text.split(/(\[[A-Z]+[A-Za-z0-9-]*\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[[A-Z]+[A-Za-z0-9-]*\]$/.test(p) ? <CitationTag key={i} tag={p.slice(1, -1)} /> : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  );
}

/** Hanging-indent bullet list with citation chips. */
export { hasHeadings };

export function HangList({ items, className = "" }: { items: string[]; className?: string }) {
  return (
    <ul className={`space-y-2.5 ${className}`}>
      {items.map((it, i) => (
        <li key={i} className="relative pl-6 [overflow-wrap:anywhere] before:absolute before:left-1 before:top-0 before:text-ink-muted before:content-['•']"><Tagged text={it} /></li>
      ))}
    </ul>
  );
}

export function BlocksView({ text, sub = "text-[14px] font-normal" }: { text: string; sub?: string }) {
  const blocks = parseBlocks(text);
  if (!blocks.length) return <p className="text-sm text-ink-muted">Not yet completed.</p>;
  return (
    <div className="space-y-8">
      {blocks.map((b, i) => (
        <div key={i} className="avoid-break">
          {b.heading && <h3 className={`mb-3 uppercase tracking-[0.12em] text-ink ${sub}`}>{b.heading}</h3>}
          {toBulletItems(b.text).length ? <HangList items={toBulletItems(b.text)} /> : <p className="text-sm text-ink-muted">No points recorded.</p>}
        </div>
      ))}
    </div>
  );
}

function BodyView({ text }: { text: string }) {
  if (hasHeadings(text)) return <BlocksView text={text} />;
  return <BulletList text={text} empty="Not yet completed." className="!space-y-3 !text-base !leading-8 break-words [overflow-wrap:anywhere]" />;
}

export const onboardingSteps = [
  { label: "Upload notes" }, { label: "Summary" }, { label: "IPS draft" }, { label: "Send to IC" }, { label: "Approve G1" },
];

export const fmtDate = (s: string) =>
  new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

export const ipsToSections = (parts: IpsPart[], override: Record<number, string> = {}): DocSection[] =>
  parts.map((p) => {
    const body = (override[p.part] ?? p.body).trim();
    return { n: p.part, title: p.title, owner: p.owner, complete: p.status !== "blank" && body.length > 0, body: <BodyView text={body} /> };
  });

/** Section text with an optional visual: profile (1) puts bullets and chart side by side. */
export function SectionBody({ n, text, extra }: { n: number; text: string; extra?: ReactNode }) {
  if (n === 1 && extra) {
    return (
      <div className="space-y-10">
        <BodyView text={text} />
        <div className="min-w-0 border-t border-hairline pt-10">{extra}</div>
      </div>
    );
  }
  return <><BodyView text={text} />{extra && <div className="mt-10 border-t border-hairline pt-10">{extra}</div>}</>;
}

/* ---------- Section 1: Profile / Goals / Concerns (+ SAA when onboarding) ---------- */
const SLIDES = ["Profile", "Goals", "Concerns"] as const;
const slideOf = (t: string) => (/concern/i.test(t) ? 2 : /objective|goal|deposit|twelve months|target/i.test(t) ? 1 : /liquidity|worr/i.test(t) ? 2 : 0);
const PROPOSED = "proposed saa";

export interface ProfileParts { profile: string; goals: string; concerns: string; saa: string }

/** Splits section 1 text into plain lines per topic. '## Profile/Goals/Concerns' blocks are honoured; otherwise bullets are sorted by topic. */
export function parseProfile(text: string): ProfileParts {
  const out: string[][] = [[], [], []];
  let saa: string[] = [];
  if (hasHeadings(text)) {
    parseBlocks(text).forEach((b) => {
      const h = (b.heading ?? "").trim().toLowerCase();
      const items = toBulletItems(b.text);
      if (h === PROPOSED) saa = items;
      else out[h === "profile" ? 0 : h === "goals" ? 1 : h === "concerns" ? 2 : b.heading ? slideOf(b.heading) : 0].push(...items);
    });
  } else toBulletItems(text ?? "").forEach((it) => out[slideOf(it)].push(it));
  return { profile: out[0].join("\n"), goals: out[1].join("\n"), concerns: out[2].join("\n"), saa: saa.join("\n") };
}
export const composeProfile = (p: ProfileParts): string =>
  composeBlocks([["Profile", p.profile], ["Goals", p.goals], ["Concerns", p.concerns], ...(p.saa.trim() ? [["Proposed SAA", p.saa] as [string, string]] : [])]);

/** Parse '• Cash: 10%' lines into [assetClass, pct]. */
export const parseSaaLines = (s: string): Record<string, number> =>
  Object.fromEntries(toBulletItems(s).flatMap((l) => { const m = l.match(/^(.+?):\s*(\d+(?:\.\d+)?)\s*%/); return m ? [[m[1].trim(), Number(m[2])]] : []; }));

/** Replace the first text block's text; every other block (including extra text blocks) is kept. */
export function withText(blocks: PackBlock[], text: string): PackBlock[] {
  const i = blocks.findIndex((b) => b.type === "text");
  if (i < 0) return [{ id: newBlockId(), type: "text", text }, ...blocks];
  return blocks.map((b, k) => (k === i ? { ...b, text } : b));
}
/** Text of the first text block (the one withText rewrites). */
export const primaryText = (blocks: PackBlock[]): string => { const b = blocks.find((x) => x.type === "text"); return b && b.type === "text" ? b.text : ""; };
const DEFAULT_BLOCKS = (n: number, chart: PackSection["chart"]): PackBlock[] => {
  const c = (k: "saa" | "taa" | "holdings"): PackBlock => ({ id: `seed-${n}-chart-${k}`, type: "chart", chart: k });
  if (chart === "saa") return [c("saa")];
  if (chart === "taa") return [{ id: `seed-${n}-table-taa`, type: "table", table: "taa" }, c("taa")];
  if (chart === "holdings") return [{ id: `seed-${n}-table-holdings`, type: "table", table: "holdings" }, c("holdings")];
  return [];
};

/** Blocks for a section; until the user saves blocks, the section's default chart/table blocks are appended (never duplicated). */
export function useSeededBlocks(clientId: string, n: number, body: string, chart?: PackSection["chart"], skipSeed = false): PackBlock[] {
  const blocks = useSectionBlocks(clientId, n, body);
  const saved = (loadRawBlocks(clientId)[n]?.length ?? 0) > 0;
  if (saved || skipSeed) return blocks;
  const extra = DEFAULT_BLOCKS(n, chart).filter((d) => !blocks.some((b) => (d.type === "chart" && b.type === "chart" && b.chart === d.chart) || (d.type === "table" && b.type === "table" && b.table === d.table)));
  return extra.length ? [...blocks, ...extra] : blocks;
}

/** Read-only render of a section's blocks: text keeps '## Heading' support, images/charts/tables come from the shared block view. */
export function SectionBlocksView({ blocks, clientId, sub }: { blocks: PackBlock[]; clientId: string; sub?: string }) {
  return (
    <div className="space-y-8">
      {blocks.map((b) => (b.type === "text" ? (b.text.trim() ? <BlocksView key={b.id} text={b.text} sub={sub} /> : null) : <BlockItem key={b.id} block={b} clientId={clientId} />))}
    </div>
  );
}

/** Export body for a section (hooks live here so the compiled document stays in step with the editor). */
export function SectionBlocksBody({ clientId, n, body, chart }: { clientId: string; n: number; body: string; chart?: PackSection["chart"] }) {
  const blocks = useSeededBlocks(clientId, n, body, chart);
  return <SectionBlocksView blocks={blocks} clientId={clientId} />;
}

export interface SaaEditor { rows: AllocationRow[]; vals: number[]; setVals: (v: number[]) => void }

function SaaPanel({ saa }: { saa: SaaEditor }) {
  const total = Math.round(saa.vals.reduce((a, b) => a + b, 0) * 10) / 10;
  const ok = total === 100;
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-start">
      <div className="min-w-0"><SaaDonut rows={saa.rows.map((r, i) => ({ ...r, saa: saa.vals[i] ?? 0 }))} /></div>
      <div className="min-w-0">
        <ul className="space-y-3">
          {saa.rows.map((r, i) => (
            <li key={r.assetClass} className="flex items-center justify-between gap-4 border-b border-hairline pb-2 text-[15px]">
              <label htmlFor={`saa-${i}`}>{r.assetClass}</label>
              <span className="flex items-center gap-2">
                <input id={`saa-${i}`} type="number" min={0} max={100} step={1} value={saa.vals[i] ?? 0}
                  onChange={(e) => saa.setVals(saa.vals.map((v, k) => (k === i ? Math.max(0, Number(e.target.value) || 0) : v)))}
                  className="w-20 border border-hairline-strong bg-surface-100 px-2 py-1.5 text-right text-[15px] text-ink" />%
              </span>
            </li>
          ))}
        </ul>
        <p className={`mt-4 text-sm ${ok ? "text-ink-muted" : "text-negative"}`}>Total {total}%{ok ? "" : ", must equal 100%"}</p>
      </div>
    </div>
  );
}

/** Section 1 as tabs (Profile, Goals, Concerns, plus SAA when onboarding). Non-text blocks sit on the Profile tab. No autoplay. */
export function ProfileCarousel({ clientId, blocks, saa }: { clientId: string; blocks: PackBlock[]; saa?: SaaEditor }) {
  const [i, setI] = useState(0);
  const parts = parseProfile(primaryText(blocks));
  const tabs = [...SLIDES, ...(saa ? (["SAA"] as const) : [])];
  const go = (d: number) => setI((v) => (v + d + tabs.length) % tabs.length);
  const slide = (t: string) => (t.trim() ? <HangList items={toBulletItems(t)} /> : <p className="text-sm text-ink-muted">Nothing recorded.</p>);
  const firstText = blocks.find((b) => b.type === "text");
  const nonText = blocks.filter((b) => b !== firstText);
  return (
    <div onKeyDown={(e) => { if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); } if (e.key === "ArrowRight") { e.preventDefault(); go(1); } }}>
      <div role="tablist" aria-label="Profile, goals and concerns" className="mb-6 flex flex-wrap gap-6 border-b border-hairline">
        {tabs.map((l, k) => (
          <button key={l} role="tab" aria-selected={i === k} tabIndex={i === k ? 0 : -1} onClick={() => setI(k)}
            className={`-mb-px cursor-pointer border-b py-3 text-[13px] uppercase tracking-[0.12em] transition-colors ${i === k ? "border-brand text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{l}</button>
        ))}
      </div>
      <div key={i} role="tabpanel" className="animate-geneva-in">
        {i === 0 ? (
          <div className="space-y-10"><div className="min-w-0">{slide(parts.profile)}</div>
            {nonText.length > 0 && <div className="min-w-0 border-t border-hairline pt-10"><SectionBlocksView blocks={nonText} clientId={clientId} /></div>}</div>
        ) : i === 1 ? slide(parts.goals) : i === 2 ? slide(parts.concerns) : saa ? <SaaPanel saa={saa} /> : null}
      </div>
    </div>
  );
}

/** Edit mode for section 1: the same tabs as the read view; only the selected tab's box (or SAA editor) is shown. Images, charts and tables sit on the Profile tab. */
export function ProfileEdit({ clientId, blocks, onChange, saa }: { clientId: string; blocks: PackBlock[]; onChange: (b: PackBlock[]) => void; saa?: SaaEditor }) {
  const [p, setP] = useState<ProfileParts>(() => parseProfile(primaryText(blocks)));
  const [i, setI] = useState(0);
  const firstText = blocks.find((b) => b.type === "text");
  const nonText = blocks.filter((b) => b !== firstText);
  const tabs = [...SLIDES, ...(saa ? (["SAA"] as const) : [])];
  const keys = ["profile", "goals", "concerns"] as const;
  const set = (k: keyof ProfileParts, v: string) => {
    const next = { ...p, [k]: v };
    setP(next);
    onChange(withText(blocks, composeProfile({ ...next })));
  };
  return (
    <div>
      <div role="tablist" aria-label="Profile, goals and concerns" className="mb-8 flex flex-wrap gap-6 border-b border-hairline">
        {tabs.map((l, k) => (
          <button key={l} role="tab" aria-selected={i === k} tabIndex={i === k ? 0 : -1} onClick={() => setI(k)}
            className={`-mb-px cursor-pointer border-b py-3 text-[13px] uppercase tracking-[0.12em] transition-colors ${i === k ? "border-brand text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{l}</button>
        ))}
      </div>
      <div key={i} role="tabpanel" className="animate-geneva-in">
        {i < 3 ? (
          <div className="space-y-8">
            <div>
              <label htmlFor={`prof-${keys[i]}`} className="mb-2 block text-[12px] uppercase tracking-[0.14em] text-ink-muted">{tabs[i]}</label>
              <textarea id={`prof-${keys[i]}`} value={p[keys[i]]} rows={8} onChange={(e) => set(keys[i], e.target.value)}
                className="block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-4 py-3 text-[16px] font-light leading-7 text-ink" />
              <p className="mt-2 text-xs text-ink-muted">One point per line.</p>
            </div>
            {i === 0 && (
              <div className="border-t border-hairline pt-8">
                <BlockEditor clientId={clientId} section={1} blocks={nonText} onChange={(nb) => onChange(firstText ? [firstText, ...nb] : nb)} />
              </div>
            )}
          </div>
        ) : saa ? <SaaPanel saa={saa} /> : null}
      </div>
    </div>
  );
}

/** Old vs new wording after Professionalise. Nothing is saved until Accept. */
export function WordingCompare({ oldText, newText, onChangeNew, onAccept, onKeep }: { oldText: string; newText: string; onChangeNew: (t: string) => void; onAccept: () => void; onKeep: () => void }) {
  const [edit, setEdit] = useState(false);
  const col = "min-w-0";
  const cap = "mb-4 text-[12px] uppercase tracking-[0.14em] text-ink-muted";
  return (
    <div className="space-y-8">
      <div className="grid gap-10 md:grid-cols-2">
        <div className={col}><p className={cap}>Your wording</p><BodyView text={oldText} /></div>
        <div className={`${col} md:border-l md:border-hairline md:pl-10`}>
          <p className={cap}>Professional wording</p>
          {edit
            ? <textarea value={newText} rows={12} aria-label="Professional wording" onChange={(e) => onChangeNew(e.target.value)} className="block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-4 py-3 text-[16px] font-light leading-7 text-ink" />
            : <BodyView text={newText} />}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onAccept}>Accept</Button>
        <Button variant="secondary" onClick={onKeep}>Keep mine</Button>
        <Button variant="secondary" onClick={() => setEdit(!edit)}>{edit ? "Preview" : "Edit"}</Button>
      </div>
    </div>
  );
}

/** `touched` = sections the RM wrote or applied from Geneva. Export bodies render the section's blocks. */
export const packToSections = (clientId: string, pack: PackSection[], override: Record<number, string> = {}, touched: number[] = [], extras: Record<number, ReactNode> = {}): DocSection[] =>
  pack.map((x) => {
    const body = override[x.n] ?? x.body;
    return { n: x.n, title: x.title, owner: x.owner, complete: touched.includes(x.n) ? body.trim().length > 0 : x.status !== "draft" && body.trim().length > 0, body: extras[x.n] ? <SectionBody n={x.n} text={body} extra={extras[x.n]} /> : <SectionBlocksBody clientId={clientId} n={x.n} body={x.body} chart={x.chart} />, wide: x.n === 1 || x.kind === "signoff" };
  });


/** Which pack sections the given role must fill in (sign-off and sources are shared by everyone). */
export const isSignoff = (x: { kind?: string }) => x.kind === "signoff";
export const isSources = (x: { title: string }) => /^sources/i.test(x.title);

const ALL_ROLES: Role[] = ["rm", "ic", "ps"];
const fmtWhen = (iso: string) => new Date(iso).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

/** Sign-off section: one box per role (RM, IC, PS). The current role's box is red-outlined; while it is unsigned, the same
 *  Type / Draw / Upload signature block the PS uses opens below the boxes. Others are read-only status. */
export function SignoffBoxes({ sigs, me, clientId, onRemove }: {
  sigs: Sigs; me: Role; clientId?: string; onRemove?: (role: Role) => void;
}) {
  const scope: Record<Role, string> = {
    rm: "Confirms client suitability, goals and the presentation of this pack.",
    ic: "Confirms the market view, portfolio health and tactical allocation.",
    ps: "Confirms the product shortlist, fees and suitability notes.",
  };
  return (
    <div>
    <div className="grid gap-5 sm:grid-cols-3">
      {ALL_ROLES.map((r) => {
        const sig = sigs[r];
        const mine = r === me;
        return (
          <div key={r} className={`avoid-break min-w-0 border p-5 ${mine ? "border-brand" : "border-hairline"}`}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-[12px] uppercase tracking-[0.12em] text-ink-muted">{ROLE_LABEL[r]}</p>
              <Badge tone={sig ? "green" : "grey"}>{sig ? "Signed" : "Pending"}</Badge>
            </div>
            <p className="mt-3 text-sm text-ink">{ROLE_PEOPLE[r].person}</p>
            <p className="mt-2 text-[13px] leading-6 text-ink-muted">{scope[r]}</p>
            <div className={`mt-4 flex h-24 items-center justify-center overflow-hidden border ${sig ? "border-hairline bg-surface-100" : "border-dashed border-hairline-strong bg-surface-200"}`}>
              {sig ? (sig.typed || !sig.dataUrl ? <span className="text-[26px] leading-tight text-ink" style={{ fontFamily: SCRIPT_FONT }}>{sig.name}</span> : <img src={sig.dataUrl} alt={`${ROLE_PEOPLE[r].person} signature`} className="max-h-full max-w-full object-contain p-2" />)
                : <span className="text-[13px] italic text-ink-muted">Digital signature pending</span>}
            </div>
            <p className="mt-2 text-[12px] text-ink-muted">{sig ? `Signed ${fmtWhen(sig.signedAt)}` : "Signed on: ____________"}</p>
            {mine && clientId && (
              <div className="no-print mt-3 flex min-h-9 items-center gap-2 text-[13px] text-ink-muted">
                {sig
                  ? <button type="button" onClick={() => onRemove?.(r)} aria-label="Remove signature" title="Remove" className="inline-flex items-center gap-1 p-2 text-ink-muted hover:text-negative"><X size={16} />Remove</button>
                  : "Sign in the box below."}
              </div>
            )}
          </div>
        );
      })}
    </div>
    {clientId && !sigs[me] && (
      <div className="no-print mt-6">
        <SignatureBlock clientId={clientId} role={me} defaultName={ROLE_PEOPLE[me].person} title={`Sign as ${ROLE_LABEL[me]}`} />
      </div>
    )}
    </div>
  );
}

const SOURCES_BY_ROLE: Record<Role, string[]> = {
  rm: [
    "Meeting notes of 12 Sep 2026 on the residential purchase and liquidity needs [NOTE-2026-09-12].",
    "Finalised Investment Policy Statement version 2, approved by the client and RM [IPS-v2].",
    "Client risk questionnaire and capacity-for-loss assessment held in the client database [KYC-2026-03].",
    "Holdings snapshot from the bank portfolio system, read-only, as of 13 Oct 2026 [HLD-20261013].",
    "Client goals, concerns and constraints as recorded in the CRM relationship file [CRM-0318].",
    "Suitability and affordability checks completed before the review meeting [SUIT-2026-10].",
  ],
  ic: [
    "UBS CIO House View, fixed income section, dated 1 Oct 2026 [CIO-2026Q4-03].",
    "Market Research Agent case result covering macro regime and rates outlook [MKT-0142].",
    "Sharpe ratio and volatility computed by the approved calculation engine [CALC-sharpe-v1].",
    "Tactical asset allocation bands and old versus new weights from the TAA model [CALC-taa-v1].",
    "Diversification and concentration analysis of the current portfolio [CALC-div-v1].",
    "Investment Committee minutes recording the approved tactical stance [IC-2026Q4-02].",
  ],
  ps: [
    "Product shortlist drawn from the approved UBS product shelf [PRD-FI-007].",
    "Fee schedules and total expense ratios confirmed with the product issuers [FEE-2026Q4].",
    "Product risk ratings and suitability notes from the product governance register [PRD-RISK-2026].",
    "Issuer credit assessment for structured and fixed income products [CRD-2026-10].",
    "Factsheets and key information documents for every recommended product [KID-2026Q4].",
    "Consistency check of the shortlist against the IC overweight in fixed income [PS-CHK-004].",
  ],
};

const SRC_HEAD: Record<Role, string> = { rm: "Relationship Manager", ic: "Investment Counsellor", ps: "Product Specialist" };

/** Section 7 text -> sources per role (only roles present in the text). Blocks are '## Relationship Manager' etc. */
function parseSources(text: string | undefined): Partial<Record<Role, string[]>> {
  const out: Partial<Record<Role, string[]>> = {};
  if (!text || !hasHeadings(text)) return out;
  parseBlocks(text).forEach((b) => {
    const r = ALL_ROLES.find((x) => SRC_HEAD[x].toLowerCase() === (b.heading ?? "").trim().toLowerCase());
    if (r) out[r] = toBulletItems(b.text);
  });
  return out;
}

/** Effective sources for one role: the saved block when present, else the seeded list. */
export const sourcesFor = (text: string | undefined, r: Role): string[] => parseSources(text)[r] ?? SOURCES_BY_ROLE[r];

/** Section 7: three equal columns. Only the viewing role's column is editable; others are read-only until their owner hands over. */
export function SourcesBoard({ clientId, me, editing: editingProp, hideEditButton = false }: { clientId: string; me: Role; editing?: boolean; hideEditButton?: boolean }) {
  const [drafts, setDrafts] = useState(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const n = pack?.find(isSources)?.n;
  const sentRm = !!useReviewRequest(clientId);
  const ps = useAllFinalised().some((f) => f.clientId === clientId);
  const ic = !!useIcHandover(clientId);
  const handed: Record<Role, boolean> = { rm: sentRm || ps, ic, ps };
  const [editingLocal, setEditing] = useState(false);
  const editing = editingProp ?? editingLocal;
  const [buf, setBuf] = useState<string[]>([]);
  const text = n ? drafts[n] : undefined;
  useEffect(() => { if (editingProp) setBuf(sourcesFor(loadPackDrafts(clientId)[n ?? -1], me)); }, [editingProp, clientId, n, me]);
  const save = (list: string[]) => {
    if (!n) return;
    const items = list.map((x) => x.trim()).filter(Boolean);
    const cur = parseSources(loadPackDrafts(clientId)[n]);
    const pairs = ALL_ROLES.map((r) => [SRC_HEAD[r], (r === me ? items : cur[r] ?? SOURCES_BY_ROLE[r]).join("\n")] as [string, string]);
    savePackDraft(clientId, n, composeBlocks(pairs), me);
  };
  return (
    <div className="grid gap-6 md:grid-cols-3">
      {ALL_ROLES.map((r) => {
        const mine = r === me;
        const items = sourcesFor(text, r);
        return (
          <section key={r} aria-label={`${SRC_HEAD[r]} sources`} className="min-w-0">
            <div className="flex items-center justify-between gap-2 border-b border-hairline-strong pb-3">
              <h3 className="text-[13px] font-normal uppercase tracking-[0.12em] text-ink">{SRC_HEAD[r]}</h3>
              {mine ? (hideEditButton ? null : <button type="button" onClick={() => { setBuf(sourcesFor(text, me)); setEditing(!editing); }} className="min-h-8 cursor-pointer border border-hairline-strong px-3 text-[12px] text-ink hover:bg-surface-300">{editing ? "Done" : "Edit"}</button>)
                : handed[r] ? <span className="flex items-center gap-1 text-[12px] text-ink-muted"><Lock size={12} />Read only</span> : null}
            </div>
            {!mine && !handed[r] ? <PendingBox owner={r} className="mt-5" />
              : mine && editing ? (
                <div className="mt-5 space-y-3">
                  {buf.map((it, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <textarea value={it} rows={3} aria-label={`Source ${i + 1}`} onChange={(e) => { const nb = buf.map((x, k) => (k === i ? e.target.value : x)); setBuf(nb); save(nb); }}
                        className="block min-w-0 flex-1 resize-y border border-hairline-strong bg-surface-100 px-3 py-2 text-[14px] leading-6 text-ink" />
                      <button type="button" onClick={() => { const nb = buf.filter((_, k) => k !== i); setBuf(nb); save(nb); }} aria-label="Remove source" className="cursor-pointer p-2 text-ink-muted hover:text-negative"><X size={16} /></button>
                    </div>
                  ))}
                  <button type="button" onClick={() => setBuf([...buf, ""])} className="min-h-8 cursor-pointer border border-hairline px-3 text-[12px] text-ink hover:bg-surface-300">Add source</button>
                </div>
              ) : <HangList items={items} className="mt-5 text-[15px] leading-7 text-ink-700" />}
          </section>
        );
      })}
    </div>
  );
}

/**
 * Single source of truth for section ticks, identical in the RM, IC and PS views of one client's pack.
 * A section is complete only after its owner marked it done and handed it over:
 *  - ps sections: PS finalised and sent to IC (G3, useAllFinalised).
 *  - ic sections: IC sent G2 to RM (useIcHandover).
 *  - rm sections: profile (1) once the RM has saved text; sources once the RM sent the request to PS; sign-off once all three signed.
 */
export function usePackStatus(clientId: string) {
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const [drafts, setDrafts] = useState(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const done = useSectionDone(clientId);
  const sent = !!useReviewRequest(clientId);
  const finalisedByPs = useAllFinalised().some((f) => f.clientId === clientId);
  const icHandedOver = !!useIcHandover(clientId);
  const complete: Record<number, boolean> = {};
  (pack ?? []).forEach((x) => {
    const text = (drafts[x.n] ?? x.body).trim();
    const marked = !!done[x.n]?.done;
    if (x.kind === "signoff") complete[x.n] = ["rm", "ic", "ps"].every((r) => sigs[r]);
    else if (isSources(x)) complete[x.n] = marked && (x.owner === "ps" ? finalisedByPs : sent || finalisedByPs);
    else if (x.owner === "ps") complete[x.n] = marked && finalisedByPs && !!text;
    else if (x.owner === "ic") complete[x.n] = marked && icHandedOver && !!text;
    else complete[x.n] = marked && !!text;
  });
  const total = pack?.length ?? 0;
  return { ready: !!pack, complete, done, doneCount: Object.values(complete).filter(Boolean).length, total };
}

/** Turn gating: a section's content is visible only to its owner, or once its owner has handed over (usePackStatus complete[n]). Sign-off is always visible. */
export const isHiddenFor = (x: { n: number; owner: Role; kind?: string }, viewer: Role, complete: Record<number, boolean>) =>
  x.kind !== "signoff" && x.owner !== viewer && !complete[x.n];

/** Quiet grey placeholder shown instead of another role's content until they hand over. */
export function PendingBox({ owner, className = "" }: { owner: Role; className?: string }) {
  return <div className={`rounded-sm bg-surface-200 px-6 py-8 text-center text-sm italic text-ink-muted ${className}`}>To be filled by {ROLE_LABEL[owner]}</div>;
}
