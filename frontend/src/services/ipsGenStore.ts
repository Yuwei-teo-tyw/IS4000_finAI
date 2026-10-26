import { useSyncExternalStore } from "react";
import { generateIpsSection, mergeIpsGenerated, appendIpsChat } from "./arcApi";
import { emitIpsGen } from "./ipsGenBus";
import { IPS_GEN_SECTIONS, type IpsGenerated, type IpsGenSectionResult } from "../types/arc";
import type { IpsGenStep } from "../components/documents/IpsGenerationTimeline";

/**
 * Module-level AI IPS generation runs, keyed by clientId. The fetch loop lives here, not in a React component, so it keeps
 * running (and keeps its progress) across route changes, sidebar unmounts and background browser tabs. Progress is index based:
 * `steps` only changes when a section resolves, so nothing depends on timers that browsers throttle.
 */
export interface IpsGenRun {
  clientId: string;
  clientName: string;
  status: "running" | "done" | "error";
  steps: IpsGenStep[];
  message: string;
  model?: string;
  /** Shown when no model was available (model is null): the backend says why. */
  modelMessage?: string;
  saved: boolean;
  savedVersion?: number;
  error?: string;
  unavailable?: boolean;
  sections: IpsGenSectionResult[];
  /** Merged unsaved draft, when the backend did not auto-save. */
  draft?: IpsGenerated;
  startedAt: number;
  finishedAt?: number;
}

const runs = new Map<string, IpsGenRun>();
const listeners = new Set<() => void>();
const BUCKET: Record<string, string> = { liquidity: "Liquidity portfolio", longevity: "Longevity portfolio", legacy: "Legacy portfolio" };

function set(clientId: string, patch: Partial<IpsGenRun>) {
  const cur = runs.get(clientId);
  if (!cur) return;
  runs.set(clientId, { ...cur, ...patch });
  listeners.forEach((fn) => fn());
}

export function getIpsRun(clientId: string): IpsGenRun | undefined { return runs.get(clientId); }
export function isIpsRunActive(clientId: string): boolean { return runs.get(clientId)?.status === "running"; }
export function subscribeIpsRuns(fn: () => void): () => void { listeners.add(fn); return () => { listeners.delete(fn); }; }
export function useIpsRun(clientId: string): IpsGenRun | undefined {
  return useSyncExternalStore(subscribeIpsRuns, () => runs.get(clientId), () => undefined);
}
/** Forget a finished run once the user has seen it (never removes a running one). */
export function dismissIpsRun(clientId: string) {
  if (runs.get(clientId)?.status === "running") return;
  if (runs.delete(clientId)) listeners.forEach((fn) => fn());
}

/** Start a run in the background. Returns false (and does nothing) if one is already running for this client. */
export function startIpsGeneration(clientId: string, clientName: string): boolean {
  if (isIpsRunActive(clientId)) return false;
  runs.set(clientId, {
    clientId, clientName, status: "running", saved: false, sections: [], startedAt: Date.now(), message: "",
    steps: IPS_GEN_SECTIONS.map((x) => ({ id: x.id, state: "pending" })),
  });
  listeners.forEach((fn) => fn());
  void run(clientId, clientName);
  return true;
}

async function run(clientId: string, clientName: string) {
  const results: IpsGenSectionResult[] = [];
  const steps: IpsGenStep[] = IPS_GEN_SECTIONS.map((x) => ({ id: x.id, state: "pending" }));
  let model: string | undefined; let modelMessage = "";
  let saved = false; let savedVersion: number | undefined;
  const snap = (message: string) => set(clientId, { steps: steps.map((x) => ({ ...x })), message, model, modelMessage, saved, savedVersion });
  const fail = (message: string, unavailable?: boolean) => {
    set(clientId, { steps: steps.map((x) => ({ ...x })), status: "error", error: message, message: "", model, modelMessage, unavailable, finishedAt: Date.now() });
  };
  emitIpsGen({ type: "start", clientId, clientName });
  for (let i = 0; i < IPS_GEN_SECTIONS.length; i++) {
    const sec = IPS_GEN_SECTIONS[i];
    steps[i].state = "active";
    snap(`Reading meeting notes · Filling ${sec.label}`);
    let r: IpsGenSectionResult;
    // Pass the draft version back so every section lands in ONE saved draft (a call without it creates a new version).
    try { r = await generateIpsSection(clientId, sec.id, savedVersion); }
    catch (e) {
      const msg = e instanceof Error ? e.message : "AI IPS generation failed.";
      steps[i].state = "pending"; fail(msg); emitIpsGen({ type: "error", clientId, message: msg }); return;
    }
    if (r.model && !model) { model = r.model; emitIpsGen({ type: "model", clientId, model }); }
    if (!r.model && r.modelMessage && !modelMessage) modelMessage = r.modelMessage;
    // The backend auto-saves a Draft version once something is generated: `saved`, `version`, `ips`.
    if (r.saved) { saved = true; savedVersion = r.version ?? r.ips?.version ?? r.saved_ips?.version ?? savedVersion; }
    emitIpsGen({ type: "section", clientId, result: r });
    set(clientId, { sections: [...(runs.get(clientId)?.sections ?? []).filter((x) => x.section !== r.section), r], model });
    if (sec.id === "allocation" && r.status !== "ok" && results.length) { steps[i].state = "pending"; steps[i].note = "Not generated"; continue; }
    if (r.status === "no_notes") { steps[i].state = "pending"; fail("No meeting notes found for this client; add notes first or create the IPS manually."); emitIpsGen({ type: "done", clientId }); return; }
    if (r.status !== "ok") { steps[i].state = "pending"; fail((!model && r.modelMessage) || r.message || "Geneva is unavailable, so the IPS was not generated.", !model); emitIpsGen({ type: "done", clientId, unavailable: !model }); return; }
    const empty = !Object.values(r.fields ?? {}).some((v) => v?.trim()) && !(r.bullets ?? []).some((b) => b?.trim()) && !Object.values(r.philosophy ?? {}).some((v) => v?.trim()) && !(r.allocation?.buckets ?? []).length;
    steps[i].state = "done";
    if (empty) steps[i].note = "Nothing stated in the notes";
    results.push(r);
  }
  const merged = mergeIpsGenerated(results);
  emitIpsGen({ type: "done", clientId, model, allocation: merged.allocation, saved, savedVersion });
  // Log in the saved IPS conversation here so it is recorded even when the sidebar is closed.
  const text = `Generated the IPS draft from the meeting notes${model ? ` with ${model}` : ""}${saved ? " and saved it" : ""}.${merged.allocation ? ` 3L allocation: ${merged.allocation.buckets.map((b) => `${BUCKET[b.id] ?? b.id} - ${b.strategy}${b.strategyName ? ` ${b.strategyName}` : ""}`).join("; ")}.` : ""}`;
  appendIpsChat(clientId, { role: "assistant", text, kind: "generation", meta: { model: model ?? null, allocation: merged.allocation ?? null } }).catch(() => {});
  set(clientId, { steps: steps.map((x) => ({ ...x })), status: "done", saved, savedVersion, model, modelMessage, message: saved ? "Saved" : "Draft ready", draft: saved ? undefined : merged, finishedAt: Date.now() });
}
