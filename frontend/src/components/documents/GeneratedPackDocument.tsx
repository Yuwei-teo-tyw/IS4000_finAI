import { useSearchParams } from "react-router-dom";
import { NumberInput } from "../../components/ui/NumberInput";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Tagged } from "../product/AssetViewParts";
import { GenevaMark } from "./GenevaMark";
import { Filter } from "lucide-react";
import { DocSection, SubHead, InlineText, EditField, Field, FreeText as PlainText, LABEL, BODY, SMALL, WRAP, EDIT_BOX, IPS_FRAME } from "./ips/parts";
import { BUCKET_VAR } from "./ips/charts";
import { BucketAllocation } from "./ips/ProportionTable";
import type { Bucket3L, ThreeLProportion } from "../../types/arc";
import { useAsync } from "../ui";
import { CitationChips } from "../ui/CitationTag";
import { registerCitations } from "../../services/citationRegistry";
import { arcApi } from "../../services/arcApi";
import { useIpsDraftExtras } from "../../services/workflowStore";
import { StrategyDonut, STRAT_COLOR } from "./ips/charts";
import { BulletTextarea } from "./BulletTextarea";
import { ProductShelfPicker } from "./ProductShelfPicker";
import { PackSignatures } from "./ips/PackSignatures";
import { toBulletItems } from "../../utils/bullets";
import { usePackHandover } from "../../services/packHandover";
import { useSignatures } from "../../services/packDraftStore";
import { loadGeneratedPack, saveGeneratedPack, type GeneratedPack, type GenTaaRow, type GenShift } from "../../pages/rm/generatedPackStore";

const NUM = `w-20 px-2 py-1 text-right text-[15px] text-ink ${EDIT_BOX}`;
/** Number box (shared NumberInput) that reports a number to the caller. */
function NumInput({ value, onValue, ...rest }: { value: number | null | undefined; onValue: (n: number) => void } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  return <NumberInput {...rest} value={value ?? ""} onFocus={(e) => { e.target.select(); }} onChange={(e) => onValue(Number(e.target.value) || 0)} />;
}
const items = (t: string) => toBulletItems(t);
const parse = <T,>(s: string | undefined, fb: T): T => { try { return s ? (JSON.parse(s) as T) : fb; } catch { return fb; } };
const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${v.toFixed(1)}%`);
const dist = (rows: GenTaaRow[], k: "existing" | "proposed" | "saa") => Object.fromEntries(rows.map((r) => [r.asset_class, Math.max(0, r[k] ?? 0)]));

/** Display-mode "Label: value": bold the short label before the first colon (<=60 chars, no sentence punctuation). */
function Lbl({ text }: { text: string }) {
  const m = /^([^:[\]\n]{1,60}):(\s[\s\S]*|)$/.exec(text);
  if (!m || /[.!?]/.test(m[1])) return <Tagged text={text} />;
  return <><strong className="font-semibold">{m[1]}:</strong>{m[2] && <Tagged text={m[2]} />}</>;
}
/** Market View shows no inline citation chips; Stored text keeps its tags until edited. */
const clean = (t: string) => t.replace(/\s*\[[A-Za-z0-9-]+\]/g, "");
const TAG = /\[[A-Za-z0-9-]+\]/;
/** Shows citation tags as chips until the user clicks to edit (then literal text); leaves untagged text always editable. */
function Cited({ value, bullets, children }: { value: string; bullets?: boolean; children: ReactNode }) {
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (editing) ref.current?.querySelector<HTMLElement>("textarea,[contenteditable]")?.focus(); }, [editing]);
  if (!editing && TAG.test(value)) {
    const lines = toBulletItems(value);
    return (
      <EditField>
        <div role="button" tabIndex={0} aria-label="Edit text" onClick={() => setEditing(true)} onKeyDown={(e) => { if (e.key === "Enter") setEditing(true); }}
          className={`cursor-text px-2 py-1 ${EDIT_BOX} ${bullets ? "" : ""}`}>
          {bullets ? <ul className="list-disc space-y-1 pl-5">{lines.map((l, i) => <li key={i} className={WRAP}><Lbl text={l} /></li>)}</ul>
            : <p className={WRAP}><Lbl text={value} /></p>}
        </div>
      </EditField>
    );
  }
  return <div ref={ref} onBlur={(e) => { if (editing && !e.currentTarget.contains(e.relatedTarget as Node | null)) setEditing(false); }}>{children}<CitationChips text={value} /></div>;
}
function FreeText(p: React.ComponentProps<typeof BulletTextarea>) { return <Cited value={p.value} bullets><BulletTextarea {...p} /></Cited>; }

/** Plain paragraph (not bullets) with citation chips until clicked. */
function Para({ value, onChange, label, placeholder }: { value: string; onChange: (v: string) => void; label: string; placeholder?: string }) {
  return <Cited value={value}><PlainText value={value} onChange={onChange} label={label} placeholder={placeholder} /></Cited>;
}
const CLASSES = ["Equities", "Fixed Income", "Cash and Cash Equivalents", "Real Estate", "Commodities", "Infrastructure", "Private Equity", "Venture Capital", "Hedge Funds", "Private Debt", "Collectibles & Fine Art", "Cryptocurrencies", "Digital Assets"];
/** House-view class names (as written in section B) to the class list above. */
const HV_CLASS: Record<string, string> = { equities: "Equities", "fixed income": "Fixed Income", cash: "Cash and Cash Equivalents", "real estate": "Real Estate", "hedge funds": "Hedge Funds", "private markets": "Private Equity" };
type StanceMap = Record<string, { stance?: string; rationale?: string }>;
/** Favoured / avoid marker: distinct shape plus colour, with the word as title and label. */
const StanceMark = ({ v }: { v: "Favoured" | "Avoid" }) => <span role="img" title={v} aria-label={v} className={`inline-block text-[14px] leading-none [print-color-adjust:exact] ${v === "Favoured" ? "text-up" : "text-down"}`}>{v === "Favoured" ? "\u25B2" : "\u25BC"}</span>;
const NOT_DOC = "Not documented";
/** Shared style for missing information: red negative token; the words stay so it is not colour-only. */
const MISSING = "!text-negative";
const B_LABEL = { liquidity: "Liquidity", longevity: "Longevity", legacy: "Legacy" } as const;
const TH = `${LABEL} py-2 pr-4 text-left align-bottom font-normal`;
const TD = "border-t border-hairline py-3 pr-4 align-top";
/** Read-only bullets with citation chips. */
const Paras = ({ text, className = "" }: { text: string; className?: string }) => <ul className={`list-disc space-y-1 pl-5 ${className}`}>{toBulletItems(text).map((l, i) => <li key={i} className={WRAP}><Lbl text={l} /></li>)}</ul>;

/** One section: content column. */
type HRow = { k: string; cls: string; holding: string; industry: string; cur: number | null; prop: number | null; rationale: string; isNew: boolean; setProp: (n: number) => void; setRat: (v: string) => void };
/** One fixed-layout holdings table per portfolio with local search + asset-class filter (filters only hide rows). */
function HoldingsTable({ rows, ro, classes: classList, tagColor }: { rows: HRow[]; ro: boolean; classes: string[]; tagColor: (t: string) => string }) {
  const tag = (t: string, strong = false) => { const c = tagColor(t); return { borderColor: c, color: strong ? "#fff" : c, background: strong ? c : `${c}14` }; };
  const [q, setQ] = useState("");
  const [cls, setCls] = useState("All");
  const [fOpen, setFOpen] = useState(false);
  const classes = [...new Set([...classList, ...rows.map((r) => r.cls)])];
  const shown = rows.filter((r) => (cls === "All" || r.cls === cls) && r.holding.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="min-w-0 space-y-3">
      {!ro && <div className="flex flex-wrap items-center gap-3 print:hidden">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search holding" aria-label="Search holdings by name" className={`w-56 px-2 py-1 text-[14px] text-ink ${EDIT_BOX}`} />
        <button type="button" onClick={() => setFOpen(!fOpen)} aria-expanded={fOpen} aria-label="Filter by asset class" title="Filter by asset class" className={`flex items-center gap-1 border px-2 py-1 ${fOpen || cls !== "All" ? "border-ink text-ink" : "border-hairline text-ink-muted"}`}><Filter size={18} />{cls !== "All" && <span className="text-[12px]">{cls}</span>}</button>
        {fOpen && <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by asset class">
          {["All", ...classes].map((c) => <button key={c} type="button" onClick={() => setCls(c)} aria-pressed={cls === c} style={c === "All" ? undefined : tag(c, cls === c)} className={`border px-2 py-0.5 whitespace-nowrap [print-color-adjust:exact] ${LABEL} ${c !== "All" ? "" : cls === c ? "border-ink text-ink" : "border-hairline text-ink-muted"}`}>{c}</button>)}
        </div>}
      </div>}
      <div className="overflow-x-auto"><table className="w-full table-fixed border-collapse text-[14px] leading-5">
        <colgroup><col className="w-[20%]" /><col className="w-[13%]" /><col className="w-[11%]" /><col className="w-[17%]" /><col className="w-[39%]" /></colgroup>
        <thead><tr><th className={TH}>Holding</th><th className={TH}>Industry</th><th className={TH}>Current Proportion</th><th className={TH}>New Proportion</th><th className={TH}>Rationale</th></tr></thead>
        <tbody>
          {shown.length === 0 && <tr><td colSpan={5} className={`${TD} text-ink-muted`}>No holdings match</td></tr>}
          {shown.map((r) => {
            const d = r.cur != null && r.prop != null ? r.prop - r.cur : 0;
            const tone = d > 0.049 ? "text-up" : d < -0.049 ? "text-down" : "";
            return (
              <tr key={r.k}>
                <td className={`${TD} ${WRAP}`}>{r.holding}
                  {r.isNew && <div className="mt-1"><span className={`whitespace-nowrap border border-negative px-1.5 text-[10px] text-negative [print-color-adjust:exact] ${LABEL}`} style={{ background: "#fdecec" }}>New product</span></div>}</td>
                <td className={`${TD} ${WRAP} ${r.industry === "-" ? "text-ink-muted" : ""}`}>{r.industry}</td>
                <td className={`${TD} tabular-nums`}>{pct(r.cur)}</td>
                <td className={`${TD} tabular-nums`}><span className={`inline-flex items-center gap-2 ${tone} [print-color-adjust:exact]`}>
                  {ro ? <span className="inline-block w-20 text-right">{pct(r.prop)}</span> : <NumInput step={0.1} min={0} max={100} aria-label={`${r.holding} new proportion`} value={r.prop} onValue={r.setProp} className={`${NUM} ${tone}`} />}
                  <span className="inline-block w-4 text-center" role="img" aria-label={d > 0.049 ? "Increase" : d < -0.049 ? "Decrease" : "Same"}>{d > 0.049 ? "\u25B2" : d < -0.049 ? "\u25BC" : "\u2013"}</span></span></td>
                <td className={TD}>{ro ? <Paras text={r.rationale} /> : <FreeText value={r.rationale} onChange={r.setRat} label={`${r.holding} rationale`} />}</td>
              </tr>);
          })}
        </tbody>
      </table></div>
    </div>);
}

/** Collapsible portfolio block: chevron toggle + title; always expanded (no toggle) in preview/print. */
function CollapsiblePortfolio({ title, ro, children }: { title: string; ro: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  const show = ro || open;
  return (
    <div className="min-w-0 space-y-8">
      {ro ? <h3 className="text-[20px] font-light leading-tight text-ink">{title}</h3> : <>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 text-left print:hidden">
          <span aria-hidden className="inline-block w-6 text-[20px] leading-none text-ink-muted">{open ? "\u25BE" : "\u25B8"}</span><h3 className="text-[20px] font-light leading-tight text-ink">{title}</h3></button>
        <div className="hidden print:block"><h3 className="text-[20px] font-light leading-tight text-ink">{title}</h3></div></>}
      <div className={show ? "min-w-0 space-y-8" : "hidden print:block"}>{children}</div>
    </div>);
}

function SecView({ n, title, children }: { n: number; id?: string; title: string; children: ReactNode }) {
  return <DocSection n={n} title={title} headingClass="text-[26px] font-light leading-tight text-ink"><div className="@container min-w-0"><div className="min-w-0 space-y-6">{children}</div></div></DocSection>;
}

export interface PackDocProps { clientId: string; clientName: string; pack: GeneratedPack; role: "rm" | "pm"; notice?: string; preview?: boolean; /** every page at once with no pager (used to export the whole pack as a PDF) */ allPages?: boolean }

/** The generated review pack as an editable IPS-style document. RM and PM edit in place. */
export function GeneratedPackDocument({ clientId, clientName, pack, role, preview = false, allPages = false }: PackDocProps) {
  const sigs = useSignatures(clientId);
  const pmHas = role === "pm" || !!usePackHandover(clientId);
  const sec = (id: string) => pack.sections.find((s) => s.id === id);
  const latest = () => loadGeneratedPack(clientId) ?? pack;
  const set = (k: string, v: string) => { const cur = latest(); saveGeneratedPack(clientId, { ...cur, edits: { ...cur.edits, [k]: v } }); };
  const ro = preview;
  useEffect(() => { registerCitations((pack.sources ?? []).map((x) => ({ id: x.id, title: x.label, note: x.status }))); }, [pack.sources]);
  useEffect(() => {
    if (clientId !== "ser" || preview || localStorage.getItem("pack-rm-comments-purged-ser")) return;
    localStorage.setItem("pack-rm-comments-purged-ser", "1");
    const { D: _d, E: _e, F: _f, ...edits } = pack.edits;
    saveGeneratedPack(clientId, { ...latest(), edits });
  }, [clientId, preview]); // eslint-disable-line react-hooks/exhaustive-deps
  const ipsRec = useAsync(() => arcApi.getIpsVersionRecord(clientId), [clientId]);
  const ipsExtras = useIpsDraftExtras(clientId);
  const rmEdit = role === "rm" && !ro;
  const prosef = ({ k, fb, label }: { k: string; fb: string; label: string }) => {
    const v = pack.edits[k] ?? fb;
    return ro ? <Paras text={v} /> : <FreeText value={v} onChange={(x) => set(k, x)} label={label} placeholder="Add narrative…" />;
  };
  const secBody = (id: string) => items(sec(id)?.body ?? "").map((l) => l.replace(/^\s*[•\-*]\s*/, ""));
  const secText = (id: string) => (pack.edits[id] != null && "ABC".includes(id) ? pack.edits[id] : secBody(id).join("\n"));

  // B: favoured / avoid asset classes, stored as JSON in edits["B.stance"] ({ class: { stance } }); seeded from the section B house-view lines until first saved.
  const ALIAS: Record<string, string> = { "Exchange-Traded Funds": "", ETFs: "" };
  // Backend per-class reasons (CIO rationale, agent view, market read), keyed by house-view class name; the short "(term, view)" text is the fallback.
  const fullWhy: Record<string, string> = Object.fromEntries(Object.entries(((sec("B")?.blocks ?? []) as { type?: string; rationales?: Record<string, string> }[]).find((b) => b.type === "market")?.rationales ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  const effStance = (edits: Record<string, string>): StanceMap => {
    if (edits["B.stance"] != null) {
      const o: StanceMap = {};
      Object.entries(parse<StanceMap>(edits["B.stance"], {})).forEach(([k, v]) => { const n = k.replace(/\s*\(.*$/, "").trim(); if (ALIAS[n] !== "" && CLASSES.includes(n)) o[n] = v; });
      return o;
    }
    const o: StanceMap = {};
    items(edits["B"] ?? secText("B")).forEach((l) => {
      const m = /^([^:[\]]{2,60}):\s*(.*)$/.exec(l); if (!m) return;
      const fav = /favou?red by|cio/i.test(m[1]), avo = /avoid|underweight/i.test(m[1]), head = /^headwinds/i.test(m[1]);
      if (!fav && !avo && !head) return;
      let d = 0, cur = ""; const parts: string[] = [];
      for (const ch of m[2]) { if (ch === "(") d++; if (ch === ")") d = Math.max(0, d - 1); if ((ch === "," || ch === ";") && d === 0) { parts.push(cur); cur = ""; } else cur += ch; }
      parts.push(cur);
      parts.forEach((p) => {
        const cls = HV_CLASS[p.replace(/\(.*$/, "").trim().toLowerCase()]; if (!cls) return;
        const why = /\(([^)]*)\)/.exec(p)?.[1]?.trim(), name = p.replace(/\(.*$/, "").trim().toLowerCase(), rationale = fullWhy[name] ?? (why ? `CIO house view rating: ${why}.` : undefined);
        if (avo || (/\bSell\b/.test(p))) o[cls] = { stance: "Avoid", rationale };
        else if (fav && /\bBuy\b/.test(p)) o[cls] = { stance: "Favoured", rationale };
      });
    });
    return o;
  };
  const stance = effStance(pack.edits);
  const setClass = (cls: string, to: "Favoured" | "Avoid" | null) => {
    const cur = effStance(latest().edits); const next = { ...cur };
    if (to) next[cls] = { ...cur[cls], stance: to }; else delete next[cls];
    set("B.stance", JSON.stringify(next));
  };
  const setWhy = (cls: string, v: string) => { const cur = effStance(latest().edits); set("B.stance", JSON.stringify({ ...cur, [cls]: { ...cur[cls], rationale: v } })); };
  const stanceSection = (title: string, which: "Favoured" | "Avoid") => {
    const mine = CLASSES.filter((c) => stance[c]?.stance === which);
    const free = CLASSES.filter((c) => stance[c]?.stance !== "Favoured" && stance[c]?.stance !== "Avoid");
    return (
      <div className="avoid-break space-y-4 border border-hairline bg-surface-100 px-5 py-5">
        <p className={LABEL}>{title}</p>
        {mine.length === 0 ? <p className={`${BODY} text-ink-muted`}>None</p> : (
          <div className="grid grid-cols-1 gap-4 @xl:grid-cols-2">
            {mine.map((c) => { const why = clean(stance[c]?.rationale ?? ""); return (
              <div key={c} className="flex min-w-0 flex-col gap-3 border border-hairline px-4 py-3">
                <div className="flex min-w-0 items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-3"><StanceMark v={which} /><span className={`${BODY} ${WRAP} font-semibold`}>{c}</span></span>
                  {!ro && <button type="button" aria-label={`Remove ${c} from ${title}`} onClick={() => setClass(c, null)} className="px-1 text-[18px] leading-none text-ink-muted hover:text-ink print:hidden">{"\u00D7"}</button>}
                </div>
                {ro ? (why.trim() ? <p className={`${SMALL} text-ink-muted ${WRAP}`}>{why}</p> : null)
                  : <Cited value={why}><PlainText rows={2} value={why} onChange={(v) => setWhy(c, v)} label={`Why ${c} is ${which === "Favoured" ? "favoured" : "avoided"}`}
                      placeholder={`Why is this class ${which === "Favoured" ? "favoured" : "avoided"}? Geneva can fill this in`} /></Cited>}
              </div>); })}
          </div>)}
        {!ro && free.length > 0 && (
          <select aria-label={`Add asset class to ${title}`} value="" onChange={(e) => { if (e.target.value) setClass(e.target.value, which); }} className={`h-9 w-full max-w-xs px-2 text-[14px] text-ink ${EDIT_BOX} print:hidden`}>
            <option value="">Add asset class</option>{free.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>)}
      </div>
    );
  };

  // B: market view. Row 1: macro phase + CIO house view; row 2: favoured, avoid; asset class stance table; then one combined themes/risks/implications block.
  // Source, house-view citation and mock-data note lines are not shown. Edits write back to the same section text.
  const marketGrid = () => {
    const text = pack.edits["B"] ?? secText("B");
    const lines = items(text);
    const setLine = (i: number, head: string, v: string) => { const next = [...lines]; next[i] = head ? `${head}: ${v}` : v; set("B", next.join("\n")); };
    const parsed = lines.map((l, i) => { const m = /^([^:[\]]{2,60}):\s*(.*)$/.exec(l); return { i, head: m ? m[1].trim() : "", body: m ? m[2] : l }; });
    const hidden = (p: { head: string; body: string }) => /^(sources?|house view|headwinds)$/i.test(p.head) || /^source:/i.test(p.body) || /\b(mock|synthetic)\b/i.test(p.body);
    const live = parsed.filter((p) => !hidden(p));
    const find = (re: RegExp) => live.find((p) => re.test(p.head));
    const macro = find(/^macro/i), cio = find(/favou?red by|cio/i), avoid = find(/avoid|underweight/i);
    const concerns = find(/^main concerns/i), impl = find(/^implications/i);
    const named = new Set([macro, cio, avoid, concerns, impl].filter(Boolean).map((p) => p!.i));
    const generic = live.filter((p) => !named.has(p.i) && (/^(market view|key themes)$/i.test(p.head) || !p.head));
    const other = live.filter((p) => !named.has(p.i) && !generic.includes(p));
    const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const [themes, ...risks] = generic;
    const tidy = (t: string) => t.replace(/\.\s*;/g, ".").replace(/;\s*;/g, ";").trim();
    const CARD = "avoid-break flex h-full min-w-0 flex-col gap-3 border border-hairline bg-surface-100 px-5 py-5";
    type P = (typeof parsed)[number];
    const write = (p: P | undefined, head: string, v: string) => { if (p) setLine(p.i, p.head, v); else if (v.trim()) set("B", [...lines, `${head}: ${v}`].join("\n")); };
    // Bullet points: sentences/semicolons (prose) or commas outside parentheses (lists). Trailing ";" is a separator only.
    const splitPts = (t: string, commas: boolean) => { const out: string[] = []; let d = 0, cur = "";
      for (let k = 0; k < t.length; k++) { const ch = t[k]; cur += ch;
        if (ch === "(" || ch === "[") d++; else if (ch === ")" || ch === "]") d = Math.max(0, d - 1);
        else if (d === 0 && (ch === ";" || ch === "\n" || (commas && ch === ",") || (ch === "." && /\s/.test(t[k + 1] ?? "") && /[A-Z]/.test(t.slice(k + 1).trimStart()[0] ?? "") && /[a-z)\]%0-9]$/.test(t.slice(0, k).slice(-1)) && !commas))) { out.push(cur); cur = ""; } }
      out.push(cur);
      return out.map((x) => x.replace(/^\s*[\u2022\-*]\s*/, "").trim().replace(commas ? /[.;,]+$/ : /[;,]+$/, "").trim()).filter((x) => x && !/^(none|no asset class is rated sell)$/i.test(x)); };
    const joinPts = (v: string, commas: boolean) => { const a = v.split("\n").map((x) => x.replace(/^\s*[\u2022\-*]\s*/, "").trim()).filter(Boolean);
      return commas ? a.join(", ") : a.map((x, i) => (i < a.length - 1 && !/[.!?;]$/.test(x) ? `${x};` : x)).join(" "); };
    const bullets = (p: P | undefined, head: string, label: string, commas: boolean, empty = "Not available") => {
      const pts = p ? splitPts(clean(tidy(p.body)), commas) : [];
      return ro ? (pts.length ? <ul className={`list-disc space-y-1 pl-5 ${BODY}`}>{pts.map((t, i) => <li key={i} className={WRAP}>{t}</li>)}</ul> : <p className={`${BODY} ${MISSING}`}>{empty}</p>)
        : <FreeText value={pts.join("\n")} onChange={(v) => write(p, head, joinPts(v, commas))} label={`Market view: ${label}`} placeholder="Add points, one per line" />;
    };
    const text1 = (p: P | undefined, head: string, label: string) => bullets(p, head, label, false);
    const prose1 = (p: P | undefined, head: string, title: string, commas = false) => <div className={CARD}><p className={LABEL}>{title}</p>{bullets(p, head, title, commas)}</div>;
    // Main concerns + risks merged into one box; edits go to the first line, the other risk lines are dropped.
    const riskLines = [concerns, ...risks].filter(Boolean) as P[];
    const riskItems = (() => { const seen: string[] = []; const out: string[] = [];
      riskLines.forEach((p) => clean(p.body).split(/;|\n/).map((x) => x.replace(/^\s*[\u2022\-*]\s*/, "").replace(/[.;\s]+$/, "").trim()).filter(Boolean).forEach((x) => { const k = norm(x); if (!seen.some((y) => y === k || y.includes(k) || k.includes(y))) { seen.push(k); out.push(x); } })); return out; })();
    const writeRisks = (v: string) => {
      const body = v.split("\n").map((x) => x.replace(/^\s*[\u2022\-*]\s*/, "").replace(/[.;\s]+$/, "").trim()).filter(Boolean).join("; ");
      const keep = riskLines[0], drop = new Set(riskLines.slice(1).map((p) => p.i));
      const next = lines.filter((_, i) => !drop.has(i));
      const idx = keep ? lines.slice(0, keep.i).filter((_, i) => !drop.has(i)).length : -1;
      if (idx >= 0) next[idx] = `${keep.head || "Main concerns"}: ${body}`; else if (body) next.push(`Main concerns: ${body}`);
      set("B", next.join("\n"));
    };
    const riskBox = () => ro ? (riskItems.length ? <ul className={`list-disc space-y-1 pl-5 ${BODY}`}>{riskItems.map((t, i) => <li key={i} className={WRAP}>{t}</li>)}</ul> : <p className={`${BODY} ${MISSING}`}>Not available</p>)
      : <FreeText value={riskItems.join("\n")} onChange={writeRisks} label="Market view: Market / Systematic Risks" placeholder="One risk per line..." />;
    const combined: { key: string; title: string; head: string; p: P | undefined }[] = [
      { key: "t", title: "Key Themes from Market Research", head: "Key themes", p: themes },
      { key: "c", title: "Market / Systematic Risks", head: "Main concerns", p: concerns ?? risks[0] },
      { key: "i", title: "Portfolio Implications", head: "Implications", p: impl },
      ...other.map((p) => ({ key: `o${p.i}`, title: p.head || "Note", head: p.head, p: p as P | undefined })),
    ].filter((c) => c.p || !ro);
    return (
      <div className="@container min-w-0 space-y-6">
        <div className="grid grid-cols-1 items-stretch gap-6 @2xl:grid-cols-2">
          {prose1(macro, "Macro phase", "Macroeconomic phase / business cycle")}
          {prose1(cio, "Favoured by the CIO house view", "CIO house view", true)}
        </div>
        {(() => { const c = combined[0]; return c ? <div className="avoid-break border border-hairline bg-surface-100 px-5 py-5 space-y-3"><p className={LABEL}>{c.title}</p>{c.key === "c" ? riskBox() : text1(c.p, c.head, c.title)}</div> : null; })()}
        {stanceSection("Favoured asset classes", "Favoured")}
        {stanceSection("Asset classes to avoid", "Avoid")}
        {combined.length > 1 && (
          <div className="avoid-break space-y-4 border border-hairline bg-surface-100 px-5 py-5">
            <p className={LABEL}>Risks and implications</p>
            <div className="space-y-4">
              {combined.slice(1).map((c) => <div key={c.key} className="space-y-1"><p className={`${BODY} font-semibold`}>{c.title}</p>{c.key === "c" ? riskBox() : text1(c.p, c.head, c.title)}</div>)}
            </div>
          </div>)}
      </div>
    );
  };

  // A-C: narrative
  const prose = (id: string) => <>
    {id === "B" ? marketGrid() : prosef({ k: id, fb: secText(id), label: `${sec(id)!.title} narrative` })}
  </>;

  // D: TAA
  const taa = parse<{ longevity?: GenTaaRow[]; legacy?: GenTaaRow[] }>(pack.edits["D.taa"], {});
  const taaRows = (b: "longevity" | "legacy") => taa[b] ?? pack.taa?.[b] ?? [];
  const setTaa = (b: "longevity" | "legacy", rows: GenTaaRow[]) => set("D.taa", JSON.stringify({ longevity: taaRows("longevity"), legacy: taaRows("legacy"), [b]: rows }));
  // C: strengths and weaknesses, scoped per bucket where a line names it. Lines naming no bucket (or Liquidity) are shown once, under Longevity.
  const swDefault = (() => {
    const o = { longevity: { s: [] as string[], w: [] as string[] }, legacy: { s: [] as string[], w: [] as string[] } };
    let mode: "s" | "w" = "s";
    items(secText("C")).forEach((l) => {
      if (/^strengths:?$/i.test(l.trim())) { mode = "s"; return; }
      if (/^weaknesses:?$/i.test(l.trim())) { mode = "w"; return; }
      o[/legacy/i.test(l) && !/longevity/i.test(l) ? "legacy" : "longevity"][mode].push(l);
    });
    return o;
  })();
  const swBox = (b: "longevity" | "legacy", k: "s" | "w", title: string) => {
    const key = `C.${b}.${k}`, v = pack.edits[key] ?? swDefault[b][k].join("\n");
    return (
      <div className="min-w-0 space-y-2"><p className={LABEL}>{title}</p>
        {ro ? (v.trim() ? <div className="avoid-break border border-hairline-strong px-3 py-2"><Paras text={v} /></div> : <p className={`${BODY} ${MISSING}`}>None recorded</p>)
          : <FreeText value={v} onChange={(x) => set(key, x)} label={`${title} for the ${b} portfolio`} placeholder="Add points, one per line" />}
      </div>);
  };
  const taaAlloc = (b: "longevity" | "legacy", label: string, roM: boolean) => {
    const rows = taaRows(b);
    const total = rows.reduce((t, r) => t + (r.proposed || 0), 0);
    const ok = Math.abs(total - 100) < 0.05;
    const upd = (i: number, patch: Partial<GenTaaRow>) => setTaa(b, rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    return (<>
        {rows.length === 0 ? <p className={`${SMALL} italic text-ink-muted`}>No SAA is saved for this bucket, so no TAA is proposed.</p> : (
          <div className="avoid-break space-y-4">
            <p className={LABEL}>Client SAA, existing TAA and proposed (new) TAA</p>
            <div className="grid grid-cols-1 gap-8 @xl:grid-cols-3">
              {([["Client SAA", "saa"], ["Existing TAA (old)", "existing"], ["Proposed TAA (new)", "proposed"]] as const).map(([t, k]) => (
                <div key={k} className="min-w-0 space-y-2"><p className={`${SMALL} text-ink-muted`}>{t}{roM && k === "proposed" && <span className="block text-[12px] italic text-negative">{allPages ? "Derived from section 3, Current Portfolio and TAA" : "Derived from the previous page (3. Current Portfolio and TAA)"}</span>}</p><StrategyDonut hideLegend allocation={dist(rows, k)} label={`${label} ${t}`} />
                  <ul className={`space-y-1 ${SMALL}`} aria-label={`${t} weights`}>{rows.filter((r) => k === "proposed" ? !roM || r.proposed > 0 : (r[k] ?? 0) > 0).map((r) => {
                    const i = rows.indexOf(r), d = r.existing == null ? 0 : r.proposed - r.existing, tone = k === "proposed" ? (d > 0.049 ? "text-up" : d < -0.049 ? "text-down" : "") : "";
                    return (
                      <li key={r.asset_class} className="flex items-center gap-2"><i className="inline-block h-3 w-3 shrink-0" style={{ background: STRAT_COLOR[r.asset_class] ?? "var(--ink-muted)" }} />{r.asset_class}
                        <span className={`ml-auto inline-flex items-center gap-2 tabular-nums ${tone} [print-color-adjust:exact]`}>
                          {k === "proposed" && !roM ? <NumInput step={0.5} min={0} max={100} aria-label={`${label} ${r.asset_class} proposed TAA`} value={r.proposed} onValue={(n) => upd(i, { proposed: n })} className={`${NUM} ${tone}`} /> : pct(r[k])}
                          {k === "proposed" && <span className="inline-block w-16 text-left" role="img" aria-label={d > 0.049 ? `Increase of ${d.toFixed(1)} points versus existing` : d < -0.049 ? `Decrease of ${Math.abs(d).toFixed(1)} points versus existing` : "Unchanged versus existing"}>{d > 0.049 ? `\u25B2 +${d.toFixed(1)}` : d < -0.049 ? `\u25BC \u2212${Math.abs(d).toFixed(1)}` : "\u2013"}</span>}
                        </span></li>); })}</ul>
                  {k === "proposed" && !roM && <p className={`${SMALL} tabular-nums ${ok ? "text-ink-muted" : "!text-negative"}`} role={ok ? undefined : "alert"}>Total {total.toFixed(1)}%{ok ? "" : ", not 100%"}</p>}</div>))}
            </div>
          </div>)}
    </>);
  };
  const taaBlock = (b: "longevity" | "legacy", label: string) => {
    const rows = taaRows(b);
    const upd = (i: number, patch: Partial<GenTaaRow>) => setTaa(b, rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    return (
      <div key={b} className="@container min-w-0 space-y-8 border-t border-hairline pt-8 first:border-t-0 first:pt-0">
        <CollapsiblePortfolio title={`${label} Portfolio`} ro={ro}>
        {taaAlloc(b, label, ro)}
        <div className="space-y-4">
          <p className={LABEL}>Current Portfolio Strengths and Weaknesses</p>
          <div className="grid grid-cols-1 gap-8 @xl:grid-cols-2">{swBox(b, "s", "Strengths")}{swBox(b, "w", "Weaknesses")}</div>
        </div>
        {rows.length > 0 && (
          <div className="space-y-4">
            <p className={LABEL}>Reasons for the proposed allocation</p>
            <div className="grid grid-cols-1 gap-6 @xl:grid-cols-2">
              {rows.map((r, i) => { const up = r.existing != null && r.proposed > r.existing + 0.049;
                if (ro && !(r.reason ?? "").trim() && !up) return null;
                return (
                  <div key={r.asset_class} className="avoid-break min-w-0 space-y-2"><p className={`${BODY} font-semibold`}>{r.asset_class}</p>
                    {ro ? ((r.reason ?? "").trim() ? <div className="avoid-break border border-hairline-strong px-3 py-2"><Paras text={r.reason ?? ""} /></div> : <p className={`${BODY} italic ${MISSING}`}>No reason recorded</p>)
                      : <FreeText value={r.reason ?? ""} onChange={(v) => upd(i, { reason: v })} label={`${label} ${r.asset_class} reason`} placeholder={up ? "No reason recorded: add one for this increase" : "Add a reason, one point per line"} />}
                  </div>); })}
            </div>
          </div>)}
        </CollapsiblePortfolio>
      </div>
    );
  };

  // E: products
  const shortlist = pack.products?.shortlist ?? [];
  const reasons = parse<Record<string, string>>(pack.edits["E.reasons"], {});
  const removed = parse<string[]>(pack.edits["E.removed"], []);
  const added = pack.addedProducts ?? [];
  const [picker, setPicker] = useState(false);
  const [sp, setSp] = useSearchParams();
  const page = Math.max(0, parseInt(sp.get("page") ?? "1", 10) - 1 || 0);
  const setPage = (f: number | ((p: number) => number)) => setSp((q) => { const n = new URLSearchParams(q); const v = typeof f === "function" ? f(Math.max(0, parseInt(q.get("page") ?? "1", 10) - 1 || 0)) : f; n.set("page", String(Math.max(0, v) + 1)); return n; }, { replace: true });
  const total = useRef(1);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (e.key === "ArrowRight") setPage((p) => Math.min(p + 1, total.current - 1));
      else if (e.key === "ArrowLeft") setPage((p) => Math.max(p - 1, 0));
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);
  const cards = [
    ...shortlist.map((it, i) => {
      const pid = (it.product as { product_id?: string }).product_id ?? "";
      const key = `s${i}`;
      return { key, id: pid, name: it.product.product_name, assetClass: it.product.asset_class, score: it.score?.total as number | undefined, riskLevel: undefined as string | undefined, added: false,
        rationale: reasons[i] ?? it.reason.text, setRationale: (v: string) => set("E.reasons", JSON.stringify({ ...reasons, [i]: v })),
        remove: () => set("E.removed", JSON.stringify([...removed, key])) };
    }).filter((c) => !removed.includes(c.key)),
    ...added.map((a, i) => ({ key: `a${a.id}`, id: a.id, name: a.name, assetClass: a.assetClass, score: a.score, riskLevel: a.riskLevel, added: true,
      rationale: a.rationale ?? "", setRationale: (v: string) => saveGeneratedPack(clientId, { ...latest(), addedProducts: added.map((x, j) => (j === i ? { ...x, rationale: v } : x)) }),
      remove: () => saveGeneratedPack(clientId, { ...latest(), addedProducts: added.filter((_, j) => j !== i) }) })),
  ];
  const lst = (t: string) => t.split(/[,;]\s*/).map((x) => x.replace(/\.$/, "").trim()).filter(Boolean);
  const missing = [...(pack.products?.missing_information ?? [])]; const incomplete: string[] = []; const disclaimers: string[] = [];
  const classify = (l: string, fromBody: boolean) => {
    const t = l.trim(); let m: RegExpMatchArray | null;
    if (!t || /^(Objective|Shelf):/i.test(t) || /^\d+\.\s/.test(t) || /^No product/i.test(t) || /^Product recommendations are unavailable/i.test(t)) return;
    if ((m = t.match(/^Missing information:\s*(.*)$/i))) { lst(m[1]).forEach((x) => !missing.includes(x) && missing.push(x)); return; }
    if ((m = t.match(/^Products with incomplete data:\s*(.*)$/i))) { lst(m[1]).forEach((x) => !incomplete.includes(x) && incomplete.push(x)); return; }
    if (fromBody && !/disclaimer/i.test(t)) return; // notes are not rendered; only the disclaimer is shown
    if (!disclaimers.includes(t)) disclaimers.push(t);
  };
  secBody("E").forEach((l) => { if (shortlist.length === 0 || /^(Missing information|Products with incomplete data):/i.test(l)) classify(l, true); });
  (pack.products?.limitations ?? []).forEach((l) => classify(l, false));
  // F: shifts
  const shifts = parse<GenShift[]>(pack.edits["F.shifts"], pack.holdings_shifts ?? []);
  const prodNew = parse<Record<string, number>>(pack.edits["F.prodNew"], {});
  const setShift = (i: number, patch: Partial<GenShift>) => set("F.shifts", JSON.stringify(shifts.map((s, j) => (j === i ? { ...s, ...patch } : s))));
  const ASSET_TAG: Record<string, string> = { equity: "#1d4ed8", "fixed income": "#047857", bond: "#047857", cash: "#b45309", "money market": "#b45309", commodit: "#a16207", "real estate": "#7c3aed", reit: "#7c3aed", alternative: "#be185d", "hedge": "#be185d", "private": "#0e7490", multi: "#4b5563" };
  const tagColor = (t: string) => { const k = Object.keys(ASSET_TAG).find((x) => t.toLowerCase().includes(x)); return k ? ASSET_TAG[k] : "#4b5563"; };
  const badge = (t: string) => { const c = tagColor(t || ""); return <span className={`inline-flex h-7 items-center whitespace-nowrap border px-2 leading-none ${LABEL}`} style={{ borderColor: c, color: c, background: `${c}14` }}>{t || "n/a"}</span>; };
  const nums = (s: GenShift) => {
    const f = (t: string) => (t.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    const a = f(String(s.proposed ?? ""));
    return { cur: s.current_pct ?? (a.length > 1 ? a[0] : null), prop: s.proposed_pct ?? (a.length ? a[a.length - 1] : null) };
  };
  const guess = (s: GenShift) => { const h = `${s.holding} ${s.ticker ?? ""}`.toLowerCase(); return /bond|treasur|fixed|note|income/.test(h) ? "Fixed Income" : /cash|money market/.test(h) ? "Cash and Cash Equivalents" : /reit|real estate|property/.test(h) ? "Real Estate" : /gold|commodit/.test(h) ? "Commodities" : /equit|etf|stock|fund|\bshares?\b/.test(h) ? "Equities" : (s.ticker || /\([A-Z.]{1,6}\)\s*$/.test(s.holding)) ? "Equities" : "Other"; };
  const order = [...new Set([...taaRows("longevity"), ...taaRows("legacy")].map((r) => r.asset_class))];

  // A: client summary, objectives, risk profile, 3L and SAA
  const aLines = secBody("A");
  const idx = (re: RegExp) => aLines.findIndex((l) => re.test(l));
  const iObj = idx(/^Objectives:/);
  const kv = (aLines.slice(0, iObj < 0 ? 8 : iObj).map((l) => /^([^:]{2,40}):\s*(.*)$/.exec(l)).filter(Boolean) as RegExpExecArray[]).map((m) => [m[1], m[2].trim()] as [string, string]);
  const demo = ipsRec?.data?.demographics?.fields ?? {};
  const have = new Set(kv.map(([k]) => k.toLowerCase()));
  const extraKv = Object.entries(demo).filter(([k, v]) => v && !have.has(k.toLowerCase())).map(([k, v]) => [k, String(v)] as [string, string]);
  const fields = [...kv, ...extraKv];
  const objDefault = iObj < 0 ? "" : aLines[iObj].replace(/^Objectives:\s*/, "").split(" | ").join("\n").replace(new RegExp(`^${NOT_DOC}$`), "");
  const riskK = (k: string) => kv.find(([x]) => x === k)?.[1] ?? NOT_DOC;
  const riskDefault = (ipsRec?.data?.risk?.bullets ?? []).join(" ") || `Risk category: ${riskK("Risk category")}. Risk limit: ${riskK("Risk limit")}. Drawdown tolerance: ${riskK("Drawdown tolerance")}.`;
  const pm3 = /^3L proportion:/; const iProp = idx(pm3);
  const propLine = iProp < 0 ? "" : aLines[iProp];
  const split = (["liquidity", "longevity", "legacy"] as const).map((b) => [b, Number(new RegExp(`${B_LABEL[b]}\\s+([\\d.]+)%`, "i").exec(propLine)?.[1] ?? 0)] as [keyof typeof BUCKET_VAR, number]);
  const saaItems = ((sec("A")?.blocks?.[0] as { items?: { bucket: string; strategy?: { code: string; name: string } | null; weights?: Record<string, number> | null }[] } | undefined)?.items) ?? [];
  const threeL = ipsRec?.data?.threeL ?? [];
  const base3L = useAsync(() => arcApi.get3L(clientId), [clientId]);
  const propSrc = (ipsExtras.proportion ?? ipsRec?.data?.threeLProportion ?? null) as ThreeLProportion | null;
  const reasonOf = (b: string) => (ipsExtras.allocationNotes?.[b] ?? threeL.find((t) => t.portfolio?.toLowerCase() === b)?.reason ?? "").trim();
  const splitPct = Object.fromEntries(split) as Record<string, number>;
  const hasSplit = split.reduce((t, [, v]) => t + v, 0) > 0;
  const baseTotal = (base3L ?? []).reduce((t, x) => t + x.amountSgd, 0);
  const buckets3L: Bucket3L[] | undefined = base3L ? base3L.map((x) => {
    const pct = propSrc?.[x.id]?.pct ?? (hasSplit ? splitPct[x.id] : x.pct);
    return { ...x, pct, amountSgd: baseTotal > 0 ? Math.round((baseTotal * pct) / 100) : x.amountSgd };
  }) : undefined;
  const proportion3L = Object.fromEntries((["liquidity", "longevity", "legacy"] as const).map((b) => [b, { pct: buckets3L?.find((x) => x.id === b)?.pct ?? 0, reason: (propSrc?.[b]?.reason ?? "").trim() || reasonOf(b) }])) as ThreeLProportion;
  const rorOf = (b: string) => threeL.find((t) => t.portfolio?.toLowerCase() === b)?.rateOfReturn ?? "";
  const Reason = ({ text }: { text: string }) => <p className={`${BODY} ${WRAP} ${text ? "" : MISSING}`}>{text ? <Tagged text={text} /> : "No reasoning recorded in the IPS."}</p>;
  const sectionA = (
    <>
      <div className="space-y-3">
        <SubHead>Client details</SubHead>
        <div className="@container min-w-0"><div className={`overflow-hidden ${IPS_FRAME}`}>
          <dl className="-ml-px -mt-px grid min-w-0 grid-cols-1 @lg:grid-cols-2 @3xl:grid-cols-3">
            {fields.map(([k, v0]) => {
              const v = pack.edits[`A.f.${k}`] ?? v0, empty = !v.trim() || v === NOT_DOC;
              return <Field key={k} label={k}>{ro || !rmEdit && role !== "pm"
                ? <span className={empty ? MISSING : ""}>{empty ? NOT_DOC : v}</span>
                : <InlineText value={empty ? "" : v} onChange={(x) => set(`A.f.${k}`, x)} label={k} placeholder={NOT_DOC} />}</Field>;
            })}
          </dl>
        </div></div>
      </div>
      <div className="space-y-2"><SubHead>Objectives</SubHead>
        {(() => { const v = pack.edits["A.obj"] ?? objDefault; return ro ? <div className={`space-y-1 ${BODY} ${WRAP} ${v.trim() ? "" : MISSING}`}>{v.trim() ? v.split("\n").filter(Boolean).map((l, i) => <p key={i}><Lbl text={l} /></p>) : NOT_DOC}</div> : <Para value={v} onChange={(x) => set("A.obj", x)} label="Objectives" placeholder={NOT_DOC} />; })()}
      </div>
      <div className="space-y-2"><SubHead>Risk profile</SubHead>
        {(() => { const v = pack.edits["A.risk"] ?? riskDefault; return ro ? <p className={`${BODY} ${WRAP}`}><Lbl text={v} /></p> : <Para value={v} onChange={(x) => set("A.risk", x)} label="Risk profile" placeholder={NOT_DOC} />; })()}
      </div>
      <div className="space-y-6">
        <SubHead>3L and SAA</SubHead>
        <div className="@container min-w-0 space-y-6">
          <div className="avoid-break space-y-2 border-t border-hairline pt-5"><p className={BODY}>3L allocation</p>
            <BucketAllocation buckets={buckets3L} proportion={proportion3L} /></div>
          {(["longevity", "legacy"] as const).map((b) => {
            const it = saaItems.find((x) => x.bucket === b);
            const w = Object.fromEntries(Object.entries(it?.weights ?? {}).filter(([, v]) => v > 0));
            return (
              <div key={b} className="avoid-break grid grid-cols-1 items-stretch gap-8 border-t border-hairline pt-5 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.6fr)]">
                <div className="flex min-w-0 flex-col gap-2">
                  <p className={LABEL}>{B_LABEL[b]} SAA</p>
                  <div className="flex flex-1 flex-col justify-center border border-ink px-4 py-3"><p className={LABEL}>Strategy</p><p className={`${BODY} ${WRAP} ${it?.strategy ? "" : MISSING}`}>{it?.strategy ? `Strategy ${it.strategy.code} - ${it.strategy.name}` : "Not available"}</p></div>
                </div>
                <div className="min-w-0 space-y-2">
                  <p className={LABEL}>SAA allocation</p>
                  {Object.keys(w).length ? <StrategyDonut allocation={w} label={`${B_LABEL[b]} SAA`} /> : <div className="flex min-w-0 flex-col items-center gap-4 sm:flex-row" data-testid="strategy-donut-empty">
                    <svg viewBox="0 0 160 160" className="h-[160px] w-[160px] shrink-0" role="img" aria-label={`${B_LABEL[b]} SAA not available`}><circle cx="80" cy="80" r="60" fill="none" stroke="var(--scale-track)" strokeWidth="26" /></svg>
                    <span className={`${BODY} text-ink-muted`}>NA</span>
                  </div>}
                </div>
                <div className="min-w-0 space-y-2"><p className={LABEL}>Strategy reasoning (from the IPS)</p><Reason text={reasonOf(b)} />
                  {rorOf(b) && <p className={`${SMALL} text-ink-muted ${WRAP}`}>{rorOf(b)}</p>}</div>
              </div>);
          })}
          <p className="text-sm italic text-brand">Liquidity Portfolio has no SAA, due to immediate funding requirements for the client.</p>
        </div>
      </div>
    </>
  );

  const pageIds = [...(["A", "B"] as const).filter((x) => sec(x)), "D", "E", "F"] as string[];
  total.current = pageIds.length;
  const cur = pageIds[Math.min(page, pageIds.length - 1)];
  const pg = (id: string, node: ReactNode) => <div key={id} data-pdf-page={id} className={cur === id || allPages ? "" : "hidden print:block"}>{node}</div>;
  const at = pageIds.indexOf(cur);
  return (
    <article className="@container mx-auto w-full min-w-0 max-w-[1400px] border border-hairline bg-surface-100 px-6 py-10 font-light text-[15px] leading-6 text-ink break-words [overflow-wrap:anywhere] sm:px-14 sm:py-16 print:max-w-none print:border-0 print:bg-transparent print:p-0 print:shadow-none">
      <GenevaMark />
      <header className="avoid-break mt-10">
        <p className={LABEL}>Quarterly review</p>
        <h1 className="mt-1 text-[34px] font-light leading-[40px]">{clientName}</h1>
        <div className="mt-4 h-px w-full bg-ink" />
      </header>

      {cur !== "A" && (
        <div role="alert" className="mt-6 flex items-center gap-3 border border-negative bg-surface px-5 py-3 text-negative print:hidden">
          <span aria-hidden="true" className="text-[22px] leading-none">{"⚠"}</span>
          <p className="text-[15px] font-semibold">VET! <span className="font-light">Market research and everything after it is AI-generated and must be vetted before it is relied on.</span></p>
        </div>)}

      {sec("A") && pg("A", <SecView n={1} id="A" title={sec("A")!.title}>{sectionA}</SecView>)}
      {sec("B") && pg("B", <SecView n={2} id="B" title={sec("B")!.title}>{prose("B")}</SecView>)}

      {pg("D", <SecView n={3} id="D" title="Current Portfolio and TAA">
                {taaBlock("longevity", "Longevity")}
        {taaBlock("legacy", "Legacy")}
      </SecView>)}

      {pg("E", <SecView n={4} id="E" title={sec("E")?.title ?? "Product Recommendations"}>
        <div className="grid grid-cols-1 gap-5 @xl:grid-cols-2">
          {cards.length === 0 && <div className="avoid-break border border-dashed border-hairline-strong px-5 py-6"><p className={LABEL}>Suitability gate</p><p className={`mt-2 ${BODY}`}>No product has passed the suitability gate.</p></div>}
          {cards.map((c) => (
            <div key={c.key} className="avoid-break flex min-w-0 flex-col gap-3 border border-hairline bg-surface-100 px-5 py-4">
              <div className="min-w-0">
                <p className={`${BODY} ${WRAP}`}>{c.name}</p>
              </div>
              <div className="flex flex-wrap gap-2">{badge(c.assetClass)}{c.score != null && <span className={`inline-flex h-7 items-center whitespace-nowrap border border-hairline-strong px-2 leading-none ${LABEL}`}>Score {Math.round(c.score)}</span>}{c.riskLevel && <span className={`inline-flex h-7 items-center whitespace-nowrap border border-negative px-2 leading-none ${LABEL} ${MISSING}`}>Risk {c.riskLevel}</span>}</div>
              <div className="min-w-0 flex-1">{ro ? <Paras text={c.rationale} /> : <FreeText value={c.rationale} onChange={c.setRationale} label={`Rationale for ${c.name}`} placeholder="Add a rationale…" />}</div>
              {!ro && <button type="button" onClick={c.remove} className={`${LABEL} self-start underline underline-offset-4`}>Remove</button>}
            </div>))}
          {!ro && <button type="button" onClick={() => setPicker(true)} className="flex min-h-[120px] items-center justify-center border border-dashed border-hairline-strong px-5 py-6 text-ink hover:bg-surface-200/40"><span className={LABEL}>Add product</span></button>}
        </div>
        {!ro && <ProductShelfPicker open={picker} onClose={() => setPicker(false)} existingIds={cards.map((c) => c.id).filter(Boolean)} onRemove={(id) => cards.find((c) => c.id === id)?.remove()} onAdd={(p) => { saveGeneratedPack(clientId, { ...latest(), addedProducts: [...added, p] }); setPicker(false); }} onAddMany={(ps) => { saveGeneratedPack(clientId, { ...latest(), addedProducts: [...added, ...ps] }); setPicker(false); }} />}
        {(missing.length > 0 || incomplete.length > 0 || disclaimers.length > 0) && (
          <div className="space-y-6">
            {missing.length > 0 && <div className="space-y-2"><p className={`${LABEL} ${MISSING}`}>Missing information ({missing.length})</p><div className="grid grid-cols-2 border-l border-t border-negative @xl:grid-cols-3">{missing.map((m) => <span key={m} className={`break-words border-b border-r border-negative px-3 py-2 ${SMALL} ${MISSING}`}>{m}</span>)}</div></div>}
            {incomplete.length > 0 && <div className="space-y-2"><p className={LABEL}>Products with incomplete data ({incomplete.length})</p><div className="grid grid-cols-3 border-l border-t border-hairline-strong @xl:grid-cols-6">{incomplete.map((m) => <span key={m} className={`break-words border-b border-r border-hairline-strong px-2 py-1.5 text-center ${SMALL} ${MISSING}`}>{m}</span>)}{Array.from({ length: (6 - (incomplete.length % 6)) % 6 }, (_, i) => <span key={`pad${i}`} aria-hidden className="border-b border-r border-hairline-strong py-1.5 text-xs">&nbsp;</span>)}</div></div>}
            {disclaimers.length > 0 && <details open={ro} className="space-y-2"><summary className={`${LABEL} cursor-pointer`}>Disclaimers</summary><ul className={`mt-2 list-disc space-y-1 pl-5 ${SMALL} text-ink-muted`}>{disclaimers.map((l, i) => <li key={i} className={WRAP}>{l}</li>)}</ul></details>}
          </div>)}
      </SecView>)}

      {pg("F", <SecView n={5} id="F" title={sec("F")?.title ?? "Individual Holdings Shifts"}>
        {shifts.length === 0 && cards.length === 0 && prosef({ k: "F", fb: secBody("F").join("\n"), label: "Holdings shifts narrative" })}
        {(["longevity", "legacy"] as const).map((b) => {
          const label = b === "longevity" ? "Longevity" : "Legacy";
          const bRows = taaRows(b);
          const inB = (s: GenShift) => (s.bucket ? s.bucket.toLowerCase() === b : bRows.some((r) => r.asset_class.toLowerCase() === (s.asset_class?.trim() || guess(s)).toLowerCase()));
          const rowsB: HRow[] = [];
          const taaNames = [...new Set(bRows.map((r) => r.asset_class))];
          const grp = (t: string) => { const x = t.toLowerCase(); return /bond|fixed|income|debt|credit/.test(x) ? "fi" : /cash|liquid|money/.test(x) ? "cash" : /real estate|reit|property/.test(x) ? "re" : /commod|gold/.test(x) ? "com" : /alternative|hedge|private/.test(x) ? "alt" : /equit|stock|share|etf|fund/.test(x) ? "eq" : ""; };
          // Normalise onto this portfolio's TAA class names so table tags and donut labels are identical strings.
          const cn = (c: string, holding = "") => { const raw = c.trim(); const l = raw.toLowerCase();
            const exact = taaNames.find((t) => t.toLowerCase() === l); if (exact) return exact;
            for (const g of [grp(raw), grp(holding)]) { if (!g) continue; const m = taaNames.find((t) => grp(t) === g); if (m) return m; }
            return raw || "Other"; };
          shifts.forEach((s, i) => { if (!inB(s)) return; const n = nums(s);
            rowsB.push({ k: `s${i}`, cls: cn(s.asset_class?.trim() || guess(s), s.holding), holding: s.holding, industry: (s.industry?.trim() && s.industry.trim().toLowerCase() !== "n/a") ? s.industry.trim() : "-", cur: n.cur, prop: s.proposed_pct ?? n.prop, rationale: s.rationale, isNew: false, setProp: (v) => setShift(i, { proposed_pct: v }), setRat: (v) => setShift(i, { rationale: v }) }); });
          cards.forEach((c) => { if (b !== "longevity") return; // products carry no bucket field: default to Longevity
            const v = prodNew[c.key];
            rowsB.push({ k: `p${c.key}`, cls: cn(c.assetClass || "Other", c.name), holding: c.name, industry: "-", cur: 0, prop: v ?? 0, rationale: c.rationale, isNew: true, setProp: (n) => set("F.prodNew", JSON.stringify({ ...prodNew, [c.key]: n })), setRat: c.setRationale }); });
          const rank = (k: string) => { const x = order.findIndex((o) => o.toLowerCase() === k.toLowerCase()); return x < 0 ? order.length : x; };
          rowsB.sort((x, y) => rank(x.cls) - rank(y.cls) || x.cls.localeCompare(y.cls) || x.holding.localeCompare(y.holding));
          const sum = rowsB.reduce((t, r) => t + (r.prop ?? 0), 0);
          const target = bRows.reduce((t, r) => t + (r.proposed || 0), 0);
          const diff = sum - target, tally = Math.abs(diff) <= 0.05;
          return (
            <div key={b} className="@container min-w-0 border-t border-hairline pt-8 first:border-t-0 first:pt-0"><CollapsiblePortfolio title={`${label} Portfolio`} ro={ro}>
              {taaAlloc(b, label, true)}
              <HoldingsTable rows={rowsB} ro={ro} classes={taaNames} tagColor={tagColor} />
              {rowsB.length > 0 && <p className={`${SMALL} tabular-nums ${tally ? "text-up" : "!text-negative"}`} role={tally ? undefined : "alert"}>Sum of new proportion: {sum.toFixed(1)}% (new TAA total {target.toFixed(1)}%){tally ? ", tallies with new TAA" : `, differs by ${diff > 0 ? "+" : "\u2212"}${Math.abs(diff).toFixed(1)} pp`}</p>}
            </CollapsiblePortfolio></div>);
        })}
        <div className="avoid-break space-y-4 border-t border-hairline pt-8">
          <SubHead>{sec("G")?.title ?? "Sign-off"}</SubHead>
          <p className={`${SMALL} text-ink-muted`}>RM: signed · PM: {sigs.pm || pmHas ? "signed" : "pending"}.</p>
          <PackSignatures sigs={sigs} clientId={clientId} readOnly={preview} pmDefault={pmHas} />
        </div>
      </SecView>)}

      <footer className="avoid-break mt-12 flex flex-wrap justify-between gap-2 border-t border-hairline pt-4 text-[12px] text-ink-muted">
        <span />
        <span>Confidential · {`PACK-${clientId.toUpperCase()}${pack.generated_at ? `-${pack.generated_at.slice(0, 10)}` : ""}`}</span>
      </footer>

      <nav aria-label="Pack pages" hidden={allPages} className="sticky bottom-0 z-30 -mx-6 mt-6 flex items-center justify-between gap-4 border-y border-black bg-black px-6 py-2 text-white sm:-mx-14 sm:px-14 print:hidden">
        <button type="button" aria-label="Previous page" disabled={at <= 0} onClick={() => setPage(at - 1)} className="border border-white px-3 py-1 text-[16px] leading-6 text-white hover:bg-white hover:text-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-white">{"\u2190"}</button>
        <p className={`min-w-0 flex-1 truncate text-center text-[16px] font-semibold text-white`} aria-live="polite">Page {at + 1} of {pageIds.length}</p>
        <button type="button" aria-label="Next page" disabled={at >= pageIds.length - 1} onClick={() => setPage(at + 1)} className="border border-white px-3 py-1 text-[16px] leading-6 text-white hover:bg-white hover:text-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-white">{"\u2192"}</button>
      </nav>
    </article>
  );
}
