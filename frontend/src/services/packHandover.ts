/** Direct RM -> Portfolio Manager handover of the review pack. The backend (/review-pack/state) is the source of truth; see pages/rm/generatedPackStore.ts for sync. */
import { useMemo, useSyncExternalStore } from "react";
import { recordPackEdit } from "./packDraftStore";
import { getPackState, loadGeneratedPack, mutateState, usePackStates, type GeneratedPack } from "../pages/rm/generatedPackStore";

export interface RmPmHandover { clientId: string; sentAt: string; rmContext?: string; pack?: GeneratedPack }
const toHandover = (clientId: string): RmPmHandover => {
  const st = getPackState(clientId);
  return { clientId, sentAt: st?.handover?.sentAt ?? "", rmContext: st?.pack?.rmContext, pack: loadGeneratedPack(clientId) ?? undefined };
};

/** Packs currently with the PM (status sent_to_pm), read from the backend states list. */
export const useAllPackHandovers = (): RmPmHandover[] => {
  const states = usePackStates();
  return useMemo(() => Object.keys(states).filter((id) => states[id]?.handover?.status === "sent_to_pm").map(toHandover), [states]);
};
/** Handover for one client while it is with the PM or handed back; undefined when not sent. */
export const usePackHandover = (clientId: string): RmPmHandover | undefined => {
  const states = usePackStates();
  return useMemo(() => (states[clientId]?.handover?.status ? toHandover(clientId) : undefined), [states, clientId]);
};
export const usePackStatus = (clientId: string) => usePackStates()[clientId]?.handover?.status ?? null;

/** Optional "Note to Portfolio Manager", kept locally per client (handover meta type is owned elsewhere). */
const noteKey = (id: string) => `arc.pmNote.${id}`;
export const loadPmNote = (clientId: string): string => { const n = getPackState(clientId)?.handover?.note; if (n?.trim()) return n; try { return localStorage.getItem(noteKey(clientId)) ?? ""; } catch { return ""; } };
export const sendPackToPm = (clientId: string, _rmContext?: string, note?: string) => {
  try { if (note?.trim()) localStorage.setItem(noteKey(clientId), note.trim()); else localStorage.removeItem(noteKey(clientId)); } catch { /* ignore */ }
  recordPackEdit(clientId, 0, "rm", "Sent to Portfolio Manager");
  mutateState(clientId, (s) => ({ ...s, handover: { status: "sent_to_pm", sentAt: new Date().toISOString(), returnedAt: null, ...(note?.trim() ? { note: note.trim() } : {}) } }), true);
};
export const withdrawPackFromPm = (clientId: string) =>
  mutateState(clientId, (s) => ({ ...s, handover: { status: null, sentAt: null, returnedAt: null, ...(s.handover?.note ? { note: s.handover.note } : {}) } }), true);
/** PM hands the generated pack back to the RM. */
export const sendPmToRm = (clientId: string) =>
  mutateState(clientId, (s) => ({ ...s, handover: { ...s.handover, status: "returned_to_rm", sentAt: s.handover?.sentAt ?? null, returnedAt: new Date().toISOString() } }), true);
export const withdrawPmToRm = (clientId: string) =>
  mutateState(clientId, (s) => ({ ...s, handover: { ...s.handover, status: "sent_to_pm", sentAt: s.handover?.sentAt ?? new Date().toISOString(), returnedAt: null } }), true);

/** PM commentary per pack section (D, E, F), stored with the pack state so the RM sees it. */
const NONE: Record<string, string> = {};
export const loadPmComments = (clientId: string): Record<string, string> => getPackState(clientId)?.pmComments ?? NONE;
export const savePmComment = (clientId: string, id: string, text: string) =>
  mutateState(clientId, (s) => ({ ...s, pmComments: { ...(s.pmComments ?? {}), [id]: text } }));
export const usePmComments = (clientId: string): Record<string, string> => usePackStates()[clientId]?.pmComments ?? NONE;

/** RM-side "PM handed the pack back" bubble: unseen until the RM opens that client's Review Pack tab. Acknowledgement is kept per hand-back (returnedAt) in localStorage. */
const ackKey = (id: string) => `arc.packBack.ack.${id}`;
const ackListeners = new Set<() => void>();
const readAck = (id: string) => { try { return localStorage.getItem(ackKey(id)) ?? ""; } catch { return ""; } };
export const ackPackReturned = (clientId: string) => {
  const at = getPackState(clientId)?.handover?.returnedAt;
  if (!at) return;
  try { localStorage.setItem(ackKey(clientId), at); } catch { /* ignore */ }
  ackListeners.forEach((f) => f());
};
export const usePackReturnedUnseen = (clientId: string): boolean => {
  const at = usePackStates()[clientId]?.handover;
  const ack = useSyncExternalStore((f) => { ackListeners.add(f); return () => { ackListeners.delete(f); }; }, () => readAck(clientId));
  return at?.status === "returned_to_rm" && !!at.returnedAt && ack !== at.returnedAt;
};
