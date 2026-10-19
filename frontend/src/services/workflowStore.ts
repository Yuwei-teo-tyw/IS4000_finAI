/**
 * Frontend-only hand-over / completion state for the two RM workflows. Same seam style as packDraftStore:
 * swap the bodies for a workflow API later.
 *   Review pack: RM -> PS -> IC -> RM (RM marks the workflow complete)
 *   IPS creation: RM -> IC -> RM (RM marks the workflow complete)
 * Each flag is keyed by clientId, kept in memory and mirrored to sessionStorage.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { arcApi } from "./arcApi";
import type { WorkflowKind, WorkflowStage, WorkflowStep } from "../types/arc";

export interface Handover { at: string }

function createFlag(name: string, seed: (clientId: string) => Handover | null) {
  const cache = new Map<string, Handover | null>();
  const listeners = new Set<() => void>();
  const storageKey = (id: string) => `wf-${name}-${id}`;

  const read = (id: string): Handover | null => {
    if (cache.has(id)) return cache.get(id) ?? null;
    let v: Handover | null = seed(id);
    try {
      const raw = sessionStorage.getItem(storageKey(id));
      if (raw !== null) v = JSON.parse(raw) as Handover | null;
    } catch { /* ignore */ }
    cache.set(id, v);
    return v;
  };
  const write = (id: string, v: Handover | null) => {
    cache.set(id, v);
    try { sessionStorage.setItem(storageKey(id), JSON.stringify(v)); } catch { /* ignore */ }
    listeners.forEach((l) => l());
  };
  const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
  const use = (clientId: string): Handover | null => useSyncExternalStore(subscribe, () => read(clientId), () => null);
  return { read, write, use };
}

const now = () => new Date().toISOString();
/** Tan Su Shan: everyone has handed over; only the RM's final completion remains. */
const SEEDED = "tss";
const seedDone = (id: string): Handover | null => (id === SEEDED ? { at: "2026-10-17T10:00:00.000Z" } : null);
const seedNone = (): Handover | null => null;

/* ---- IPS creation: RM -> IC -> RM ---- */
const ipsRequest = createFlag("ips-request", seedNone);
const ipsIc = createFlag("ips-ic", seedNone);
const ipsDone = createFlag("ips-complete", seedNone);
/** RM has sent the IPS draft to the IC (null = not sent). */
export const useIpsRequest = ipsRequest.use;
export const sendIpsToIc = (clientId: string) => ipsRequest.write(clientId, { at: now() });
/** Withdraw only while the IC has not handed back. */
export const withdrawIpsToIc = (clientId: string) => { if (!ipsIc.read(clientId)) ipsRequest.write(clientId, null); };
/** IC has proposed the SAA and handed the IPS back to the RM. */
export const useIpsIcHandover = ipsIc.use;
export const sendIpsIcToRm = (clientId: string) => ipsIc.write(clientId, { at: now() });
/** RM reviewed the IC proposal and marked the IPS workflow complete. */
export const useIpsComplete = ipsDone.use;
export const setIpsComplete = (clientId: string, done = true) => ipsDone.write(clientId, done ? { at: now() } : null);

/* ---- Review pack: RM -> PS -> IC -> RM ---- */
const packPs = createFlag("pack-ps", seedDone);
const packIc = createFlag("pack-ic", seedDone);
const packRm = createFlag("pack-rm", seedDone);
const packDone = createFlag("pack-complete", seedNone);
/** RM sent the pack to the PS. */
export const usePackPsRequest = packPs.use;
export const sendPackToPs = (clientId: string) => packPs.write(clientId, { at: now() });
/** PS finalised products and handed to the IC. */
export const usePackIcHandover = packIc.use;
export const sendPackToIc = (clientId: string) => packIc.write(clientId, { at: now() });
/** IC approved sections 2-5 and handed back to the RM. */
export const usePackRmHandover = packRm.use;
export const sendPackToRm = (clientId: string) => packRm.write(clientId, { at: now() });
/** RM's final completion of the review pack workflow (the only thing that reaches 100%). */
export const useWorkflowComplete = packDone.use;
export const setWorkflowComplete = (clientId: string, done = true) => packDone.write(clientId, done ? { at: now() } : null);

/* ---- Stage for the Client Book ---- */
const PACK_LABELS: Pick<WorkflowStep, "role" | "label">[] = [
  { role: "rm", label: "RM opens pack" }, { role: "ps", label: "PS products" }, { role: "ic", label: "IC sections 2-5" }, { role: "rm", label: "RM completes" },
];
const IPS_LABELS: Pick<WorkflowStep, "role" | "label">[] = [
  { role: "rm", label: "RM fills IPS" }, { role: "ic", label: "IC proposes SAA" }, { role: "rm", label: "RM completes" },
];

/** Pure derivation. `done[i]` says whether step i is finished; percent is 100 only when the last (RM completion) step is done. */
export function buildStage(kind: WorkflowKind, done: boolean[]): WorkflowStage {
  const labels = kind === "pack" ? PACK_LABELS : IPS_LABELS;
  const firstOpen = done.findIndex((d) => !d);
  const steps: WorkflowStep[] = labels.map((l, i) => ({ ...l, state: done[i] ? "done" : i === firstOpen ? "current" : "todo" }));
  const count = done.filter(Boolean).length;
  return { kind, steps, percent: firstOpen === -1 ? 100 : Math.min(99, Math.round((count / labels.length) * 100)) };
}

/**
 * Stage of the client's active workflow. Pass `kind` to force one; otherwise a started pack wins,
 * then a started IPS, then the client's phase (Onboarding = IPS, Monitoring = pack).
 */
export function useWorkflowStage(clientId: string, kind?: WorkflowKind): WorkflowStage {
  const iReq = useIpsRequest(clientId), iIc = useIpsIcHandover(clientId), iDone = useIpsComplete(clientId);
  const pPs = usePackPsRequest(clientId), pIc = usePackIcHandover(clientId), pRm = usePackRmHandover(clientId), pDone = useWorkflowComplete(clientId);
  const [onboarding, setOnboarding] = useState(false);
  useEffect(() => {
    let live = true;
    arcApi.getClient(clientId).then((c) => { if (live) setOnboarding(c?.status === "Onboarding Phase"); });
    return () => { live = false; };
  }, [clientId]);

  const packStarted = !!(pPs || pIc || pRm || pDone);
  const ipsStarted = !!(iReq || iIc || iDone);
  const k: WorkflowKind = kind ?? (packStarted ? "pack" : ipsStarted ? "ips" : onboarding ? "ips" : "pack");
  return k === "pack"
    ? buildStage("pack", [!!pPs, !!pIc, !!pRm, !!pDone])
    : buildStage("ips", [!!iReq, !!iIc, !!iDone]);
}
