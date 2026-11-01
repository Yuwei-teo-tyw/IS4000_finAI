/** Persists the AI-generated review pack per client so the RM can edit it and the PM can open it after handover. Shape = backend POST /review-pack/generate. */
import { useSyncExternalStore } from "react";
import { arcApi } from "../../services/arcApi";

export interface GenSection { id: string; title: string; body: string; blocks?: unknown[] }
export interface GenShift { holding: string; action: string; proposed: string; rationale: string; risks: string[] | string; ticker?: string; bucket?: string; asset_class?: string; industry?: string; current_pct?: number | null; proposed_pct?: number | null }
export interface GenTaaRow { asset_class: string; existing: number | null; saa: number; proposed: number; reason?: string }
export interface GeneratedPack {
  sections: GenSection[];
  taa?: { longevity?: GenTaaRow[]; legacy?: GenTaaRow[] };
  products?: { shortlist?: { rank: number; product: { product_name: string; asset_class: string; sub_asset_class?: string | null }; score?: { total: number }; reason: { text: string } }[]; missing_information?: string[]; limitations?: string[] } | null;
  holdings_shifts?: GenShift[];
  sources?: { id: string; label: string; status: string }[];
  narrative_status?: { llm_texts_accepted?: number; llm_texts_total?: number; detail?: string };
  generated_at?: string;
  /** Whose TAA and holding shifts the pack holds: "pm" = proposed for the PM (made when the PM opens the pack); "previous" = the last
   *  approved review's, read-only; "none" = first review, nothing yet. Packs from before this field count as "pm". */
  taa_stage?: "pm" | "previous" | "none";
  /** Why there is no new TAA yet (stages "previous" and "none"). */
  taa_note?: string | null;
  prior_review?: { approved_at: string; generated_at?: string | null } | null;
  /** RM edits: section id -> replacement text (A, B, C, G) or RM commentary (D, E, F). */
  edits: Record<string, string>;
  rmContext?: string;
  /** Products the PM/RM added to section E from the shelf. Absent on older packs. */
  addedProducts?: { id: string; name: string; assetClass: string; riskLevel?: string; score?: number; rationale?: string }[];
}

/** One opaque state object per client, stored on the backend (/review-pack/state/{id}); localStorage is only an instant cache. */
export interface PackHandoverMeta { status: "sent_to_pm" | "returned_to_rm" | null; sentAt: string | null; returnedAt: string | null; note?: string }
/** A past pack kept in `history` (older states have no such field). */
export interface PackHistoryEntry { id: string; pack: Omit<GeneratedPack, "edits">; edits?: Record<string, string>; handover?: PackHandoverMeta; pmComments?: Record<string, string>; approvedAt?: string | null }
export interface PackState { pack?: Omit<GeneratedPack, "edits">; edits?: Record<string, string>; handover?: PackHandoverMeta; pmComments?: Record<string, string>; approvedAt?: string | null; history?: PackHistoryEntry[] }
export type PackStatusLabel = "Draft" | "Sent to PM" | "Returned by PM" | "Approved";
export const packStatusLabel = (e: { handover?: PackHandoverMeta; approvedAt?: string | null }): PackStatusLabel =>
  e.approvedAt ? "Approved" : e.handover?.status === "sent_to_pm" ? "Sent to PM" : e.handover?.status === "returned_to_rm" ? "Returned by PM" : "Draft";

const CACHE_KEY = "rm-review-pack-states-v2";
const listeners = new Set<() => void>();
let states: Record<string, PackState> = (() => { try { return JSON.parse(localStorage.getItem(CACHE_KEY) ?? "{}"); } catch { return {}; } })();
let syncError: string | null = null;
const version: Record<string, number> = {};
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const dirty = new Set<string>();
let firstSync = true;
/** Monotonic counter; touched[id] = last local mutation / write completion. A poll that started before that must not overwrite local state (stale echo would resurrect a withdrawn handover). */
let seq = 0;
const touched: Record<string, number> = {};

const emit = () => { try { localStorage.setItem(CACHE_KEY, JSON.stringify(states)); } catch { /* ignore */ } listeners.forEach((l) => l()); };
const setErr = (e: string | null) => { if (e !== syncError) { syncError = e; listeners.forEach((l) => l()); } };
const ERR = "Could not save to server. Your changes are kept in this browser and will retry.";

async function flush(clientId: string) {
  const t = timers.get(clientId); if (t) { clearTimeout(t); timers.delete(clientId); }
  const v = version[clientId] ?? 0;
  try {
    const st = states[clientId];
    if (st) await arcApi.putReviewPackState(clientId, st as Record<string, unknown>); else await arcApi.deleteReviewPackState(clientId);
    touched[clientId] = ++seq;
    if ((version[clientId] ?? 0) === v) dirty.delete(clientId);
    setErr(null);
  } catch { setErr(ERR); timers.set(clientId, setTimeout(() => void flush(clientId), 5000)); }
}
/** Local change: update memory + cache now, write through to the backend (debounced unless immediate). */
export function mutateState(clientId: string, fn: (s: PackState) => PackState | null, immediate = false) {
  const next = fn(states[clientId] ?? {});
  states = { ...states }; if (next) states[clientId] = next; else delete states[clientId];
  version[clientId] = (version[clientId] ?? 0) + 1; dirty.add(clientId); touched[clientId] = ++seq;
  emit();
  const t = timers.get(clientId); if (t) clearTimeout(t);
  if (immediate) void flush(clientId); else timers.set(clientId, setTimeout(() => void flush(clientId), 700));
}
export async function refreshPackStates() {
  const s0 = seq;
  try {
    const remote = (await arcApi.getReviewPackStates()) as Record<string, PackState>;
    const next: Record<string, PackState> = { ...remote };
    for (const id of new Set([...dirty, ...Object.keys(touched).filter((k) => touched[k] > s0)])) { if (states[id]) next[id] = states[id]; else delete next[id]; }
    if (firstSync) { for (const id of Object.keys(states)) if (!(id in remote) && !dirty.has(id)) { next[id] = states[id]; void arcApi.putReviewPackState(id, states[id] as Record<string, unknown>).catch(() => setErr(ERR)); } firstSync = false; }
    if (JSON.stringify(next) !== JSON.stringify(states)) { states = next; emit(); }
    if (dirty.size === 0) setErr(null);
  } catch { /* backend down: keep cache; saves report errors */ }
}
let poll: ReturnType<typeof setInterval> | null = null;
const onFocus = () => void refreshPackStates();
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  if (listeners.size === 1) { void refreshPackStates(); poll = setInterval(() => void refreshPackStates(), 5000); window.addEventListener("focus", onFocus); }
  return () => { listeners.delete(fn); if (listeners.size === 0) { if (poll) clearInterval(poll); poll = null; window.removeEventListener("focus", onFocus); } };
};
export const usePackStates = () => useSyncExternalStore(subscribe, () => states);
export const useSyncError = () => useSyncExternalStore(subscribe, () => syncError);
export const getPackState = (clientId: string): PackState | undefined => states[clientId];

/**
 * MOCK: replace with Geneva + Product Specialist agent selection.
 * Intended workflow (NOT implemented here): Geneva selects products for the pack from current market conditions
 * (house view / CIO asset-class views) plus the Product Specialist (backend product_recommender) agent's ranked
 * recommendations, and writes them to the pack's section E; the RM/PM then accepts, edits or removes each one.
 * For now the Jane Fraser pack opens with these illustrative picks so the section is not empty. Ids/names are real
 * entries from the product shelf (backend product_recommender/data/shelf.json); picks are Conservative (risk cap 2),
 * no hedge funds / private markets, and lean to Fixed income (house view: Buy) plus a cash buffer. Not agent output.
 * Applied only to the "jfr" pack (backend book id "jft") while it has no agent shortlist and no added products at all.
 */

const packCache = new Map<string, { st: PackState; value: GeneratedPack | null }>();
export function loadGeneratedPack(clientId: string): GeneratedPack | null {
  const st = states[clientId];
  if (!st?.pack) return null;
  const hit = packCache.get(clientId);
  if (hit && hit.st === st) return hit.value;
  const value = { ...st.pack, edits: st.edits ?? {} } as GeneratedPack;
  packCache.set(clientId, { st, value });
  return value;
}
const archive = (s: PackState): PackHistoryEntry[] => [
  ...(s.history ?? []),
  ...(s.pack ? [{ id: `${s.pack.generated_at ?? "pack"}-${Date.now()}`, pack: s.pack, edits: s.edits, handover: s.handover, pmComments: s.pmComments, approvedAt: s.approvedAt }] : []),
];
/** Archive the current pack into history (nothing is overwritten) and optionally start a new one. */
export function startNewPack(clientId: string, pack: GeneratedPack | null) {
  mutateState(clientId, (s) => {
    const history = archive(s);
    if (!pack) return history.length ? { history } : null;
    const { edits, ...rest } = pack;
    return { history, pack: rest, edits };
  }, true);
}
/** Remove a history pack unless Approved (Draft, Sent to PM, Returned by PM). */
export function discardHistoryPack(clientId: string, id: string) {
  mutateState(clientId, (s) => ({ ...s, history: (s.history ?? []).filter((h) => h.id !== id || packStatusLabel(h) === "Approved") }), true);
}
/** Delete the current pack unless Approved; also drops its handover so it leaves the PM inbox. Empty state deletes on the backend. */
export function deleteCurrentPack(clientId: string) {
  mutateState(clientId, (s) => {
    if (s.approvedAt) return s;
    const history = s.history ?? [];
    return history.length ? { history } : null;
  }, true);
}
/** Make a history pack the current one (the current pack goes to history). Callers must not do this while the current pack is with the PM. */
export function openHistoryPack(clientId: string, id: string) {
  mutateState(clientId, (s) => {
    const h = (s.history ?? []).find((x) => x.id === id); if (!h) return s;
    const rest = { ...s, history: (s.history ?? []).filter((x) => x.id !== id) };
    const history = archive(rest);
    return { history, pack: h.pack, edits: h.edits ?? {}, handover: h.handover, pmComments: h.pmComments, approvedAt: h.approvedAt };
  }, true);
}
export const getPackHistory = (st: PackState | undefined): PackHistoryEntry[] => st?.history ?? [];
export function saveGeneratedPack(clientId: string, pack: GeneratedPack | null) {
  if (!pack) { startNewPack(clientId, null); return; }
  const { edits, ...rest } = pack;
  mutateState(clientId, (s) => ({ ...s, pack: rest, edits }));
}
export const useGeneratedPack = (clientId: string) => { usePackStates(); return loadGeneratedPack(clientId); };

