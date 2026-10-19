/**
 * Frontend-only cross-role workflow state (RM -> PS -> IC), persisted in sessionStorage with in-tab pub/sub.
 * Same seam style as packDraftStore: swap the bodies for a saved-state API later, keep the hooks.
 */
import { useSyncExternalStore } from "react";
import type { MarketRow, Role } from "../types/arc";
import { recordPackEdit, ipsKey, seedPackState } from "./packDraftStore";
import { notify, clientNameOf, PERSON } from "./notificationStore";
import { clients } from "../mock/data";

export { ipsKey };

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
  notify({ to: "ps", from: "rm", clientId, kind: "pack", message: `${PERSON.rm} sent the Review pack for ${clientNameOf(clientId)}` });
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
  notify({ to: "ic", from: "ps", clientId, kind: "pack", message: `${PERSON.ps} sent the Review pack for ${clientNameOf(clientId)}` });
};

/* ---- 4. Active IPS version per client (used by the chatbot: "Using IPS v2") ---- */
const activeIps = createStore<Record<string, number>>("wf-active-ips", {});
/** Explicit choice if the RM made one, else null (callers fall back to the client's latest approved version). */
export const useActiveIps = (clientId: string): number | null => activeIps.use()[clientId] ?? null;
export const setActiveIps = (clientId: string, version: number) => activeIps.write({ ...activeIps.read(), [clientId]: version });

/* ---- 5. IC saved progress per client (products ticked for the TAA, TAA values); section text goes through packDraftStore ---- */
export interface IcProgress { products?: string[]; taa?: number[]; /** IC's written reason per asset class (keyed by assetClass) for the TAA change */ taaReasons?: Record<string, string>; /** edited holding weights (% of portfolio) by holding id */ holdings?: Record<string, number>; /** onboarding request builders: 3L bucket amounts, SAA split and chosen template */ threeL?: number[]; saa?: number[]; saaTemplate?: string; savedAt?: string }
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
  notify({ to: "rm", from: "ic", clientId, kind: "pack", message: `${PERSON.ic} sent the Review pack for ${clientNameOf(clientId)}` });
};
export const withdrawIcToRm = (clientId: string) => {
  const { [clientId]: _drop, ...rest } = icHandover.read();
  icHandover.write(rest);
};

/* ---- 7. IPS creation workflow (RM -> IC -> RM). Section content lives in the pack stores under ipsKey(clientId). ---- */
export interface IpsRequest { clientId: string; sentAt: string }
const ipsRequests = createStore<IpsRequest[]>("wf-ips-requests", []);
export const useIpsRequests = () => ipsRequests.use();
export const useIpsRequest = (clientId: string) => ipsRequests.use().find((r) => r.clientId === clientId);
export const sendIpsToIc = (clientId: string) => {
  recordPackEdit(ipsKey(clientId), 0, "rm", "Handed over to Investment Counsellor");
  ipsRequests.write([...ipsRequests.read().filter((r) => r.clientId !== clientId), { clientId, sentAt: new Date().toISOString() }]);
  notify({ to: "ic", from: "rm", clientId, kind: "ips", message: `${PERSON.rm} sent the IPS for ${clientNameOf(clientId)}` });
};
export const withdrawIpsToIc = (clientId: string) => ipsRequests.write(ipsRequests.read().filter((r) => r.clientId !== clientId));

const ipsIcHandover = createStore<Record<string, IcHandover>>("wf-ips-ic-handover", {});
export const useIpsIcHandover = (clientId: string): IcHandover | undefined => ipsIcHandover.use()[clientId];
export const useIpsIcHandovers = (): Record<string, IcHandover> => ipsIcHandover.use();
export const sendIpsIcToRm = (clientId: string) => {
  recordPackEdit(ipsKey(clientId), 0, "ic", "Handed over to Relationship Manager");
  ipsIcHandover.write({ ...ipsIcHandover.read(), [clientId]: { sentAt: new Date().toISOString() } });
  notify({ to: "rm", from: "ic", clientId, kind: "ips", message: `${PERSON.ic} sent the IPS for ${clientNameOf(clientId)}` });
};

/* ---- 8. Final completion, set only by the RM ("Complete workflow") ---- */
const ipsComplete = createStore<Record<string, { at: string }>>("wf-ips-complete", {});
export const useIpsComplete = (clientId: string): boolean => !!ipsComplete.use()[clientId];
export const setIpsComplete = (clientId: string, complete = true) => {
  const { [clientId]: _drop, ...rest } = ipsComplete.read();
  ipsComplete.write(complete ? { ...rest, [clientId]: { at: new Date().toISOString() } } : rest);
  if (complete) recordPackEdit(ipsKey(clientId), 0, "rm", "IPS workflow completed");
};
const packComplete = createStore<Record<string, { at: string }>>("wf-workflow-complete", {});
export const useWorkflowComplete = (clientId: string): boolean => !!packComplete.use()[clientId];
export const setWorkflowComplete = (clientId: string, complete = true) => {
  const { [clientId]: _drop, ...rest } = packComplete.read();
  packComplete.write(complete ? { ...rest, [clientId]: { at: new Date().toISOString() } } : rest);
  if (complete) recordPackEdit(clientId, 0, "rm", "Review pack workflow completed");
};

/* ---- 9. Client Book stage: derived from the stores above ---- */
export interface WorkflowStep { role: Role; label: string; state: "done" | "current" | "todo" }
export interface WorkflowStage { kind: "pack" | "ips"; steps: WorkflowStep[]; percent: number }
const toSteps = (defs: [Role, string, boolean][]): WorkflowStep[] => {
  let currentSet = false;
  return defs.map(([role, label, done]) => {
    if (done) return { role, label, state: "done" as const };
    if (!currentSet) { currentSet = true; return { role, label, state: "current" as const }; }
    return { role, label, state: "todo" as const };
  });
};
/** kind omitted: Onboarding clients show the IPS flow, Monitoring clients the Review Pack flow. Percent reaches 100 only after setIpsComplete / setWorkflowComplete. */
export function useWorkflowStage(clientId: string, kind?: "pack" | "ips"): WorkflowStage {
  const sentPack = !!useReviewRequest(clientId);
  const psDone = useAllFinalised().some((f) => f.clientId === clientId);
  const icPack = !!useIcHandover(clientId);
  const packDone = useWorkflowComplete(clientId);
  const sentIps = !!useIpsRequest(clientId);
  const icIps = !!useIpsIcHandover(clientId);
  const ipsDone = useIpsComplete(clientId);
  const k = kind ?? (clients.find((c) => c.id === clientId)?.status === "Onboarding Phase" ? "ips" : "pack");
  const steps = k === "ips"
    ? toSteps([["rm", "RM fills IPS", sentIps], ["ic", "IC proposes SAA", icIps], ["rm", "RM reviews", ipsDone]])
    : toSteps([["rm", "RM drafts pack", sentPack], ["ps", "PS products", psDone], ["ic", "IC sections", icPack], ["rm", "RM reviews", packDone]]);
  const complete = k === "ips" ? ipsDone : packDone;
  const doneN = steps.filter((x) => x.state === "done").length;
  const hasCurrent = steps.some((x) => x.state === "current");
  const percent = complete ? 100 : Math.min(99, Math.round((doneN / steps.length) * 100 + (hasCurrent ? 10 : 0)));
  return { kind: k, steps, percent };
}

/* ---- Demo seed: Tan Su Shan has RM -> PS -> IC -> RM done; only the RM's "Complete workflow" remains. Runs once per session and never overwrites. ---- */
function seedTss() {
  const id = "tss";
  try {
    if (sessionStorage.getItem("wf-seeded-tss")) return;
    sessionStorage.setItem("wf-seeded-tss", "1");
    const addTo = <T,>(key: string, init: T, put: (cur: T) => T) => {
      let cur = init;
      try { const raw = sessionStorage.getItem(key); if (raw) cur = JSON.parse(raw) as T; } catch { /* ignore */ }
      sessionStorage.setItem(key, JSON.stringify(put(cur)));
    };
    const at = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();
    addTo<ReviewRequest[]>("wf-review-requests", [], (c) => (c.some((r) => r.clientId === id) ? c : [...c, { clientId: id, sentAt: at(300), priority: "normal" }]));
    addTo<Record<string, FinalisedList>>("wf-finalised", {}, (c) => (c[id] ? c : { ...c, [id]: { clientId: id, sentAt: at(200), items: [] } }));
    addTo<Record<string, IcHandover>>("wf-ic-handover", {}, (c) => (c[id] ? c : { ...c, [id]: { sentAt: at(100) } }));
    seedPackState(id, {
      done: { 1: "rm", 2: "ic", 3: "ic", 4: "ic", 5: "ps", 7: "rm", 8: "ic" },
      signatures: {
        ps: { name: "David", dataUrl: "", typed: true, signedAt: at(190) },
        ic: { name: "Wei Lun", dataUrl: "", typed: true, signedAt: at(90) },
      },
    });
  } catch { /* ignore */ }
}
seedTss();
