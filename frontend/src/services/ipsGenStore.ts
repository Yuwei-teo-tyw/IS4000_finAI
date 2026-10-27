import { useSyncExternalStore } from "react";
import { streamIpsGeneration, mergeIpsGenerated, appendIpsChat } from "./arcApi";
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

const controllers = new Map<string, AbortController>();
/** User cancel: aborts the stream; sections that already finished stay in the run, the backend does not save a draft. */
export function cancelIpsGeneration(clientId: string) {
  controllers.get(clientId)?.abort();
}

async function run(clientId: string, clientName: string) {
  const ctrl = new AbortController();
  controllers.set(clientId, ctrl);
  const byId = new Map<string, IpsGenSectionResult>();
  const steps: IpsGenStep[] = IPS_GEN_SECTIONS.map((x) => ({ id: x.id, state: "active" })); // sections run concurrently
  let model: string | undefined; let modelMessage = "";
  let saved = false; let savedVersion: number | undefined;
  const label = (id: string) => IPS_GEN_SECTIONS.find((s) => s.id === id)?.label ?? id;
  const waiting = () => { const l = steps.filter((x) => x.state === "active").map((x) => label(x.id)); return l.length ? `Reading meeting notes · Filling ${l.join(", ")}` : "Finishing up"; };
  const snap = (message: string) => set(clientId, { steps: steps.map((x) => ({ ...x })), message, model, modelMessage, saved, savedVersion });
  const fail = (message: string, unavailable?: boolean) => {
    set(clientId, { steps: steps.map((x) => ({ ...x })), status: "error", error: message, message: "", model, modelMessage, unavailable, finishedAt: Date.now() });
  };
  const ordered = () => IPS_GEN_SECTIONS.map((x) => byId.get(x.id)).filter((r): r is IpsGenSectionResult => !!r && r.status === "ok");
  emitIpsGen({ type: "start", clientId, clientName });
  snap(waiting());
  const onSection = (r: IpsGenSectionResult) => {
    byId.set(r.section, r);
    if (r.model && !model) { model = r.model; emitIpsGen({ type: "model", clientId, model }); }
    if (!r.model && r.modelMessage && !modelMessage) modelMessage = r.modelMessage;
    emitIpsGen({ type: "section", clientId, result: r });
    const step = steps.find((x) => x.id === r.section);
    if (step) {
      if (r.status !== "ok") { step.state = "pending"; step.note = r.status === "error" ? "Failed" : r.status === "no_notes" ? "No meeting notes" : "Not generated"; }
      else {
        step.state = "done";
        const empty = !Object.values(r.fields ?? {}).some((v) => v?.trim()) && !(r.bullets ?? []).some((b) => b?.trim()) && !Object.values(r.philosophy ?? {}).some((v) => v?.trim()) && !(r.allocation?.buckets ?? []).length;
        if (empty) step.note = "Nothing stated in the notes";
      }
    }
    set(clientId, { sections: [...(runs.get(clientId)?.sections ?? []).filter((x) => x.section !== r.section), r], model });
    snap(waiting());
  };
  let final: Awaited<ReturnType<typeof streamIpsGeneration>> = null;
  try { final = await streamIpsGeneration(clientId, { onSection }, ctrl.signal); }
  catch (e) {
    controllers.delete(clientId);
    const cancelled = e instanceof DOMException && e.name === "AbortError";
    const msg = cancelled ? "Generation cancelled." : e instanceof Error ? e.message : "AI IPS generation failed.";
    steps.forEach((x) => { if (x.state === "active") x.state = "pending"; });
    fail(msg); emitIpsGen({ type: "error", clientId, message: msg }); return;
  }
  controllers.delete(clientId);
  const missing = IPS_GEN_SECTIONS.filter((x) => !byId.has(x.id)).map((x) => x.label);
  steps.forEach((x) => { if (x.state === "active") { x.state = "pending"; x.note = "Not finished"; } });
  const okResults = ordered();
  if (!final) { // the stream died before the final line: show what finished and what did not
    const msg = `The connection to Geneva dropped. ${okResults.length} of ${IPS_GEN_SECTIONS.length} sections finished${missing.length ? `; not finished: ${missing.join(", ")}` : ""}. Nothing was saved.`;
    set(clientId, { draft: okResults.length ? mergeIpsGenerated(okResults) : undefined });
    fail(msg); emitIpsGen({ type: "error", clientId, message: msg }); return;
  }
  if (final.model && !model) model = final.model;
  if (!modelMessage && final.modelMessage) modelMessage = final.modelMessage;
  if (final.saved) { saved = true; savedVersion = final.version ?? undefined; }
  if (!okResults.length) {
    const first = [...byId.values()][0];
    if (first && [...byId.values()].every((r) => r.status === "no_notes")) { fail("No meeting notes found for this client; add notes first or create the IPS manually."); emitIpsGen({ type: "done", clientId }); return; }
    fail((!model && modelMessage) || first?.message || "Geneva is unavailable, so the IPS was not generated.", !model); emitIpsGen({ type: "done", clientId, unavailable: !model }); return;
  }
  const results = okResults;
  const failed = IPS_GEN_SECTIONS.filter((x) => byId.get(x.id)?.status === "error").map((x) => x.label);
  if (final.error) set(clientId, { error: final.error });
  if (failed.length) set(clientId, { error: `${failed.join(", ")} could not be generated; the other sections were kept.` });
  const merged = mergeIpsGenerated(results);
  emitIpsGen({ type: "done", clientId, model, allocation: merged.allocation, saved, savedVersion });
  // Log in the saved IPS conversation here so it is recorded even when the sidebar is closed. Reasoning is part of the text so it survives reload.
  const head = `Generated the IPS draft from the meeting notes${model ? ` with ${model}` : ""}${saved ? " and saved it" : ""}.${merged.allocation ? ` 3L allocation: ${merged.allocation.buckets.map((b) => `${BUCKET[b.id] ?? b.id} - ${b.strategy}${b.strategyName ? ` ${b.strategyName}` : ""}`).join("; ")}.` : ""}`;
  const prop = merged.proportion ? ` 3L proportion: ${(["liquidity", "longevity", "legacy"] as const).map((k) => `${BUCKET[k].replace(" portfolio", "")} ${merged.proportion![k].pct}%`).join(", ")}.` : "";
  const why = results.filter((r) => r.reasoning?.length).map((r) => `${IPS_GEN_SECTIONS.find((s) => s.id === r.section)?.label ?? r.section} reasoning:\n${r.reasoning!.map((l) => `- ${l}`).join("\n")}`).join("\n\n");
  const text = `${head}${prop}${why ? `\n\n${why}` : ""}`;
  appendIpsChat(clientId, { role: "assistant", text, kind: "generation", meta: { model: model ?? null, allocation: merged.allocation ?? null, proportion: merged.proportion ?? null, reasoning: Object.fromEntries(results.filter((r) => r.reasoning?.length).map((r) => [r.section, r.reasoning])) } }).catch(() => {});
  set(clientId, { steps: steps.map((x) => ({ ...x })), status: "done", saved, savedVersion, model, modelMessage, message: saved ? "Saved" : "Draft ready", draft: saved ? undefined : merged, finishedAt: Date.now() });
}
