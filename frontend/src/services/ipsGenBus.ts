import type { IpsAllocation, IpsGenSectionResult } from "../types/arc";

/** Tiny pub/sub between the IPS page (which runs AI IPS generation) and the Geneva sidebar chat (which shows the evidence). */
export type IpsGenEvent =
  | { type: "start"; clientId: string; clientName?: string; model?: string }
  | { type: "section"; clientId: string; result: IpsGenSectionResult }
  | { type: "model"; clientId: string; model?: string; unavailable?: boolean }
  | { type: "done"; clientId: string; model?: string; allocation?: IpsAllocation; saved?: boolean; savedVersion?: number; unavailable?: boolean }
  | { type: "error"; clientId: string; message: string };

type Listener = (e: IpsGenEvent) => void;
const listeners = new Set<Listener>();
/** Events emitted while no one listens (e.g. the sidebar is still mounting) are replayed to the next subscriber for this long. */
const REPLAY_MS = 5000;
let recent: { at: number; e: IpsGenEvent }[] = [];

export function emitIpsGen(e: IpsGenEvent) {
  const now = Date.now();
  recent = [...recent.filter((r) => now - r.at < REPLAY_MS), { at: now, e }];
  listeners.forEach((fn) => fn(e));
}

export function subscribeIpsGen(fn: Listener): () => void {
  listeners.add(fn);
  const now = Date.now();
  // A start event can fire before the sidebar finishes opening: replay recent ones so nothing is lost.
  recent.filter((r) => now - r.at < REPLAY_MS).forEach((r) => fn(r.e));
  return () => { listeners.delete(fn); };
}
