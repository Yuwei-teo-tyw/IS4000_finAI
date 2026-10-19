/**
 * Frontend-only cross-role workflow state (RM -> PS -> IC), persisted in sessionStorage with in-tab pub/sub.
 * Same seam style as packDraftStore: swap the bodies for a saved-state API later, keep the hooks.
 */
import { useSyncExternalStore } from "react";
import type { MarketRow } from "../types/arc";
import { recordPackEdit } from "./packDraftStore";

/** One-time reset of stale demo state in this tab, so Jane Fraser and David Solomon start from the seeded zero progress. Bump SEED_VERSION to reset again. */
const SEED_VERSION = "2";
try {
  if (sessionStorage.getItem("wf-seed-version") !== SEED_VERSION) {
    Object.keys(sessionStorage).filter((k) => k.startsWith("wf-") || /[-_:](jfr|dso)$/.test(k)).forEach((k) => sessionStorage.removeItem(k));
    sessionStorage.setItem("wf-seed-version", SEED_VERSION);
  }
} catch { /* ignore */ }

function createStore<T>(storageKey: string, initial: T) {
  const listeners = new Set<() => void>();
  let cache: { raw: string | null; value: T } | null = null;
  const read = (): T => {
    let raw: string | null = null;
    try { raw = sessionStorage.getItem(storageKey); } catch { /* ignore */ }
    if (cache && cache.raw === raw) return cache.value;
    let value = initial;
    try { if (raw) value = JSON.parse(raw) as T; } catch { /* ignore */ }
    cache = { raw, value };
    return value;
  };
  const write = (value: T) => {
    try { sessionStorage.setItem(storageKey, JSON.stringify(value)); } catch { /* ignore */ }
    listeners.forEach((l) => l());
  };
  const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
  const use = () => useSyncExternalStore(subscribe, read);
  return { read, write, use };
}

/* ---- 1. RM -> PS review requests (RM presses "Send to Product Specialist") ---- */
export interface ReviewRequest { clientId: string; sentAt: string; priority: "normal" | "high" }
const requests = createStore<ReviewRequest[]>("wf-review-requests", []);
export const useReviewRequests = () => requests.use();
export const useReviewRequest = (clientId: string) => requests.use().find((r) => r.clientId === clientId);
export const sendReviewRequest = (clientId: string, priority: ReviewRequest["priority"] = "normal") => {
  recordPackEdit(clientId, 0, "rm", "Handed over to Product Specialist");
  requests.write([...requests.read().filter((r) => r.clientId !== clientId), { clientId, sentAt: new Date().toISOString(), priority }]);
};
export const withdrawReviewRequest = (clientId: string) => requests.write(requests.read().filter((r) => r.clientId !== clientId));

/* ---- 2. PS ticked products (shared by the research chat and the Product Shelf; key = MarketRow.product, the product name) ---- */
const selection = createStore<Record<string, MarketRow[]>>("wf-ps-selection", {});
export const loadSelection = (clientId: string): MarketRow[] => selection.read()[clientId] ?? [];
export const saveSelection = (clientId: string, rows: MarketRow[]) => selection.write({ ...selection.read(), [clientId]: rows });
export const useSelection = (clientId: string): MarketRow[] => selection.use()[clientId] ?? [];
export const toggleSelection = (clientId: string, row: MarketRow) => {
  const cur = loadSelection(clientId);
  saveSelection(clientId, cur.some((r) => r.product === row.product) ? cur.filter((r) => r.product !== row.product) : [...cur, row]);
};

/* ---- 3. PS finalised list sent to IC (G3), each product with the PS's typed reason ---- */
export interface FinalisedItem extends MarketRow { reason: string }
export interface FinalisedList { clientId: string; sentAt: string; items: FinalisedItem[] }
const finalised = createStore<Record<string, FinalisedList>>("wf-finalised", {});
export const useFinalised = (clientId: string): FinalisedList | undefined => finalised.use()[clientId];
export const useAllFinalised = (): FinalisedList[] => Object.values(finalised.use());
export const sendFinalised = (clientId: string, items: FinalisedItem[]) => {
  recordPackEdit(clientId, 0, "ps", "Handed over to Investment Counsellor");
  finalised.write({ ...finalised.read(), [clientId]: { clientId, sentAt: new Date().toISOString(), items } });
};

/* ---- 4. Active IPS version per client (used by the chatbot: "Using IPS v2") ---- */
const activeIps = createStore<Record<string, number>>("wf-active-ips", {});
/** Explicit choice if the RM made one, else null (callers fall back to the client's latest approved version). */
export const useActiveIps = (clientId: string): number | null => activeIps.use()[clientId] ?? null;
export const getActiveIps = (clientId: string): number | null => activeIps.read()[clientId] ?? null;
export const setActiveIps = (clientId: string, version: number) => activeIps.write({ ...activeIps.read(), [clientId]: version });

/* ---- 5. IC saved progress per client (products ticked for the TAA, TAA values); section text goes through packDraftStore ---- */
export interface IcProgress { products?: string[]; taa?: number[]; /** IC's written reason per asset class (keyed by assetClass) for the TAA change */ taaReasons?: Record<string, string>; /** edited holding weights (% of portfolio) by holding id */ holdings?: Record<string, number>; /** onboarding 3L bucket amounts (S$) */ buckets?: number[]; /** onboarding SAA weights, template id + class weights */ saaTemplate?: string; saa?: number[]; savedAt?: string }
const icProgress = createStore<Record<string, IcProgress>>("wf-ic-progress", {});
export const useIcProgress = (clientId: string): IcProgress => icProgress.use()[clientId] ?? {};
export const loadIcProgress = (clientId: string): IcProgress => icProgress.read()[clientId] ?? {};
/** Merge a patch and stamp savedAt. Call only on an explicit Save so unsaved edits can be told apart. */
export const saveIcProgress = (clientId: string, patch: Partial<IcProgress>) =>
  icProgress.write({ ...icProgress.read(), [clientId]: { ...icProgress.read()[clientId], ...patch, savedAt: new Date().toISOString() } });

/* ---- 6. IC -> RM handover (IC presses "Send to RM" once G2 content is ready) ---- */
export interface IcHandover { sentAt: string }
const icHandover = createStore<Record<string, IcHandover>>("wf-ic-handover", {});
export const useIcHandover = (clientId: string): IcHandover | undefined => icHandover.use()[clientId];
export const sendIcToRm = (clientId: string) => {
  recordPackEdit(clientId, 0, "ic", "Handed over to Relationship Manager");
  icHandover.write({ ...icHandover.read(), [clientId]: { sentAt: new Date().toISOString() } });
};
export const withdrawIcToRm = (clientId: string) => {
  const { [clientId]: _drop, ...rest } = icHandover.read();
  icHandover.write(rest);
};

/* ---- 7. Onboarding IPS: RM -> IC (RM sends the draft), IC -> RM (IC returns parts 2 and 4), activation ---- */
const ipsSent = createStore<Record<string, { sentAt: string }>>("wf-ips-sent", {});
export const useIpsSent = (clientId: string): { sentAt: string } | undefined => ipsSent.use()[clientId];
export const useAllIpsSent = (): string[] => Object.keys(ipsSent.use());
export const sendIpsToIc = (clientId: string) => ipsSent.write({ ...ipsSent.read(), [clientId]: { sentAt: new Date().toISOString() } });

/** RM pulls a sent IPS back to keep editing (also clears any IC return). */
export const withdrawIpsFromIc = (clientId: string) => {
  const { [clientId]: _s, ...sentRest } = ipsSent.read(); ipsSent.write(sentRest);
  const { [clientId]: _r, ...retRest } = ipsReturned.read(); ipsReturned.write(retRest);
};

const ipsReturned = createStore<Record<string, { sentAt: string }>>("wf-ips-returned", {});
export const useIpsReturned = (clientId: string): boolean => !!ipsReturned.use()[clientId];
/** The IC can only return an IPS the RM actually sent. */
export const returnIpsToRm = (clientId: string) => { if (ipsSent.read()[clientId]) ipsReturned.write({ ...ipsReturned.read(), [clientId]: { sentAt: new Date().toISOString() } }); };
export const useAllIpsReturned = (): string[] => Object.keys(ipsReturned.use());
export const loadReturned = (): string[] => Object.keys(ipsReturned.read());
export const isIpsReturned = (clientId: string): boolean => !!ipsReturned.read()[clientId];

/**
 * RULE: a client leaves the Onboarding Phase only when onboarding progress is full (draft sent, returned by the IC, approved at G1)
 * AND an IPS is active. `activateIps` is the single way to get there; `isActivated` re-checks every condition.
 */
const activated = createStore<Record<string, boolean>>("wf-ips-activated", {});
export const isActivated = (clientId: string): boolean =>
  !!activated.read()[clientId] && !!ipsSent.read()[clientId] && !!ipsReturned.read()[clientId] && activeIps.read()[clientId] !== undefined;
export const useActivated = (clientId: string): boolean => {
  const a = activated.use()[clientId]; const s = ipsSent.use()[clientId]; const r = ipsReturned.use()[clientId]; const v = activeIps.use()[clientId];
  return !!a && !!s && !!r && v !== undefined;
};
/** G1 approval: needs the IPS sent to and returned by the IC. Sets the active IPS and activates the client in one step. Returns false if the steps are incomplete. */
export const activateIps = (clientId: string, version: number): boolean => {
  if (!ipsSent.read()[clientId] || !ipsReturned.read()[clientId]) return false;
  setActiveIps(clientId, version);
  activated.write({ ...activated.read(), [clientId]: true });
  return true;
};
