import type { IpsData, IpsNoteRef, IpsThreeLItem } from "../../../types/arc";
import type { AllocBucketId, ThreeLMeta } from "./Allocation";
import { groupsFromBackend, groupsToBackend, parseGoals, serializeGoals } from "./goals";
import { normaliseLifeEvents, type IpsLifeEvent, type IpsTarget } from "./ipsTypes";
import { toBullets } from "./parts";

/** Pure mapping between the backend structured IPS JSON (`data`, see backend schemas.py) and what the editor holds. */
const BUCKETS: AllocBucketId[] = ["liquidity", "longevity", "legacy"];
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
const STRAT: Record<string, string> = { A: "Fixed Income", B: "Income", C: "Yield", D: "Balanced", E: "Growth", F: "Equities" };

export const rulesToBullets = (r: { title: string; text: string }[]) => r.map((x) => (x.title ? `${x.title}: ${x.text}` : x.text));
/** Inverse of rulesToBullets: "Title: text" lines -> {title,text}. A line without a short label keeps an empty title. */
export function bulletsToRules(body: string): { title: string; text: string }[] {
  return body.split("\n").map((l) => l.replace(/^\s*[•\-*]\s*/, "").trim()).filter(Boolean).map((l) => {
    const m = /^([^:.]{1,48}):\s+(\S[\s\S]*)$/.exec(l);
    return m ? { title: m[1].trim(), text: m[2].trim() } : { title: "", text: l };
  });
}
const clean = (o?: Record<string, string> | null) => Object.fromEntries(Object.entries(o ?? {}).filter(([, v]) => typeof v === "string" && v.trim()));

export interface IpsSeed {
  text: { 1?: string; 3?: string; 5?: string };
  targets: IpsTarget[]; lifeEvents: IpsLifeEvent[]; reviewRules: { title: string; text: string }[];
  demo: Record<string, string>; risk: Record<string, string>;
  philosophy: { approach?: string; believes?: string; avoids?: string; statement?: string };
  allocation: Partial<Record<AllocBucketId, string>>; allocationNotes: Record<string, string>;
  allocationMeta: Partial<Record<AllocBucketId, ThreeLMeta>>; proposed: Partial<Record<AllocBucketId, string>>;
  notIncluded: string[]; rmSignedDate?: string; rmSignatureImage?: string;
  model?: string | null; modelMessage?: string;
}

/** Backend `data` -> editor seed. Goals go through groupsFromBackend; threeL becomes strategy + reason + meta (source, default, conflict). */
export function seedFromData(d: IpsData): IpsSeed {
  const goals = groupsFromBackend(d.goals);
  const allocation: IpsSeed["allocation"] = {}, allocationNotes: Record<string, string> = {}, allocationMeta: IpsSeed["allocationMeta"] = {}, proposed: IpsSeed["proposed"] = {};
  for (const b of d.threeL ?? []) {
    const id = String(b.portfolio ?? "").toLowerCase() as AllocBucketId;
    if (!BUCKETS.includes(id) || !b.strategy) continue;
    allocation[id] = b.strategy; proposed[id] = b.strategy;
    if (b.reason) allocationNotes[id] = b.reason;
    allocationMeta[id] = { strategy: b.strategy, reason: b.reason, default: !!b.default,
      source: b.source ? { id: b.source.noteId, date: b.source.date, title: b.source.title } : undefined, conflict: b.conflict ?? undefined };
  }
  const rules = (d.reviewRules ?? []).filter((r) => r && (r.title || r.text));
  return {
    text: {
      ...(goals ? { 1: serializeGoals(goals) } : {}),
      ...(d.risk?.bullets ? { 3: d.risk.bullets.join("\n") } : {}),
      ...(rules.length ? { 5: rulesToBullets(rules).join("\n") } : {}),
    },
    targets: (d.targets ?? []).map((t, i) => ({ id: `t-${i}`, amount: t.amount ?? undefined, currency: t.currency ?? undefined, horizonYears: t.horizonYears ?? undefined, text: t.text ?? "", source_note: t.source_note ?? undefined })),
    lifeEvents: normaliseLifeEvents((d.lifeEvents ?? []).map((e) => ({ ...e, date: e.date ?? undefined, year: e.year ?? undefined, source_note: e.source_note ?? undefined }))),
    reviewRules: rules,
    demo: clean(d.demographics?.fields), risk: clean(d.risk?.fields), philosophy: { ...(d.philosophy ?? {}) },
    allocation, allocationNotes, allocationMeta, proposed,
    notIncluded: (d.notIncluded ?? []).filter((x) => typeof x === "string" && x.trim()),
    rmSignedDate: d.rmSignedDate, rmSignatureImage: d.rmSignatureImage, model: d.model, modelMessage: d.modelMessage,
  };
}

/** The editor state to persist. `base` is the loaded `data` (untouched fields such as evidence, riskScore, model are kept). */
export interface IpsEditState {
  text: Record<number, string>; targets?: IpsTarget[]; lifeEvents?: IpsLifeEvent[];
  demo: Record<string, string>; risk: Record<string, string>; philosophy: Record<string, string | undefined>;
  allocation: Partial<Record<AllocBucketId, string>>; allocationNotes: Record<string, string>;
  allocationMeta: Partial<Record<AllocBucketId, ThreeLMeta>>; notIncluded: string[];
  rmSignedDate?: string; rmSignature?: string;
}

const num = (v: unknown): number | null => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : null; };
const noteRef = (n: IpsNoteRef | string | null | undefined): IpsNoteRef | null => (n && typeof n === "object" ? n : null);

export function buildIpsData(base: IpsData | undefined, e: IpsEditState): IpsData {
  const prev = new Map<string, IpsThreeLItem>((base?.threeL ?? []).map((b) => [String(b.portfolio).toLowerCase(), b]));
  const threeL: IpsThreeLItem[] = BUCKETS.filter((b) => e.allocation[b]).map((b) => {
    const code = e.allocation[b]!, old = prev.get(b);
    return { ...old, portfolio: cap(b), strategy: code, strategyName: STRAT[code] ?? old?.strategyName ?? "", reason: e.allocationNotes[b] ?? old?.reason ?? "",
      default: old && old.strategy === code ? !!old.default : false, source: old?.source ?? null, conflict: old?.conflict ?? null };
  });
  const goals = groupsToBackend(parseGoals(e.text[1] ?? ""));
  const targets = (e.targets ?? []).filter((t) => (t.text ?? "").trim() || t.amount).map((t) => ({
    amount: t.amount == null || t.amount === "" ? null : t.amount, currency: t.currency ?? null, horizonYears: t.horizonYears ?? null, text: t.text ?? "", source_note: noteRef(t.source_note) }));
  const lifeEvents = (e.lifeEvents ?? []).map((x) => ({ id: x.id, date: x.date ?? null, year: num(x.year), label: x.label, detail: x.detail ?? "", source_note: noteRef(x.source_note), manual: !!x.manual }));
  const reviewRules = e.text[5] !== undefined ? bulletsToRules(e.text[5]) : base?.reviewRules;
  return {
    ...base,
    goals, targets, lifeEvents, ...(reviewRules ? { reviewRules } : {}), threeL,
    notIncluded: e.notIncluded,
    demographics: { fields: { ...(base?.demographics?.fields ?? {}), ...clean(e.demo) } },
    philosophy: { ...(base?.philosophy ?? {}), ...Object.fromEntries(Object.entries(e.philosophy).filter(([, v]) => v !== undefined)) },
    risk: { fields: { ...(base?.risk?.fields ?? {}), ...clean(e.risk) }, bullets: e.text[3] !== undefined ? toBullets(e.text[3]) : base?.risk?.bullets ?? [] },
    ...(e.rmSignedDate ? { rmSignedDate: e.rmSignedDate } : {}),
    ...(e.rmSignature ? { rmSignatureImage: e.rmSignature } : {}),
  };
}
