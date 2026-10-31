/** Frontend-only store for review-pack section text the RM wrote or applied from Geneva. Same seam style as arcApi: swap for a saved draft API later. */
import { useSyncExternalStore } from "react";
import type { PackBlock, Role } from "../types/arc";

const EVENT = "geneva:packdraft";
const key = (clientId: string) => `pack-draft-${clientId}`;

export type PackDrafts = Record<number, string>;

export function loadPackDrafts(clientId: string): PackDrafts {
  try { const raw = sessionStorage.getItem(key(clientId)); return raw ? (JSON.parse(raw) as PackDrafts) : {}; } catch { return {}; }
}

/* ---- Raw block storage (used by packBlocksStore; kept here so savePackDraft can keep blocks in sync without a cycle). ---- */
export const BLOCKS_EVENT = "geneva:packblocks";
export const blocksKey = (clientId: string) => `pack-blocks-${clientId}`;
export function loadRawBlocks(clientId: string): Record<number, PackBlock[]> {
  try { const raw = sessionStorage.getItem(blocksKey(clientId)); return raw ? (JSON.parse(raw) as Record<number, PackBlock[]>) : {}; } catch { return {}; }
}
export function writeRawBlocks(clientId: string, next: Record<number, PackBlock[]>) {
  try { sessionStorage.setItem(blocksKey(clientId), JSON.stringify(next)); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(BLOCKS_EVENT, { detail: clientId }));
}
const newId = () => `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

const subTo = (event: string) => (fn: () => void) => { window.addEventListener(event, fn); return () => window.removeEventListener(event, fn); };
const subHist = subTo("geneva:packhist"), subDone = subTo("geneva:packdone"), subSig = subTo("geneva:packsig");

/** `opts.skipBlocks` is for packBlocksStore, which writes blocks itself. Otherwise, when blocks exist, the FIRST text block takes the new text (image/chart/table blocks are kept). */
export function savePackDraft(clientId: string, section: number, text: string, by?: Role, opts?: { skipBlocks?: boolean; force?: boolean }) {
  // Identical text is a no-op: no write, no history entry, done flag stays. `force` is for block edits that do not change the text.
  if (!opts?.force && (loadPackDrafts(clientId)[section] ?? "") === text) return;
  if (!opts?.skipBlocks) {
    const all = loadRawBlocks(clientId);
    const blocks = all[section];
    if (blocks && blocks.length) {
      const i = blocks.findIndex((b) => b.type === "text");
      const next: PackBlock[] = i >= 0
        ? blocks.map((b, j) => (j === i ? { id: b.id, type: "text" as const, text } : b))
        : [{ id: newId(), type: "text", text }, ...blocks];
      writeRawBlocks(clientId, { ...all, [section]: next });
    }
  }
  recordPackEdit(clientId, section, by);
  if (getSectionDone(clientId)[section]?.done) writeDone(clientId, { ...getSectionDone(clientId), [section]: { ...getSectionDone(clientId)[section], done: false, at: new Date().toISOString() } });
  try { sessionStorage.setItem(key(clientId), JSON.stringify({ ...loadPackDrafts(clientId), [section]: text })); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: clientId }));
}

export function subscribePackDrafts(clientId: string, fn: (d: PackDrafts) => void): () => void {
  const on = (e: Event) => { if ((e as CustomEvent<string>).detail === clientId) fn(loadPackDrafts(clientId)); };
  window.addEventListener(EVENT, on);
  return () => window.removeEventListener(EVENT, on);
}

/* ---- Edit history (per client, newest first). section 0 = handed over. ---- */
export interface PackEdit { at: string; role: Role; section: number; summary?: string }
const HIST_EVENT = "geneva:packhist";
const histKey = (clientId: string) => `pack-hist-${clientId}`;
const histCache = new Map<string, { raw: string | null; value: PackEdit[] }>();

/** Role is the first URL segment (/rm, /pm), same rule as useRole() in AppShell. */
function currentRole(): Role {
  try { const seg = window.location.pathname.split("/")[1]; return seg === "pm" ? seg : "rm"; } catch { return "rm"; }
}
function getPackHistory(clientId: string): PackEdit[] {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(histKey(clientId)); } catch { /* ignore */ }
  const c = histCache.get(clientId);
  if (c && c.raw === raw) return c.value;
  let value: PackEdit[] = [];
  try { if (raw) value = JSON.parse(raw) as PackEdit[]; } catch { /* ignore */ }
  histCache.set(clientId, { raw, value });
  return value;
}
/** Appends an entry; same role+section within 60s updates the latest entry instead. */
export function recordPackEdit(clientId: string, section: number, by?: Role, summary?: string) {
  const role = by ?? currentRole();
  const now = new Date();
  const list = [...getPackHistory(clientId)];
  const top = list[0];
  if (top && top.role === role && top.section === section && now.getTime() - new Date(top.at).getTime() < 60_000) {
    list[0] = { ...top, at: now.toISOString(), ...(summary ? { summary } : {}) };
  } else {
    list.unshift({ at: now.toISOString(), role, section, ...(summary ? { summary } : {}) });
  }
  try { sessionStorage.setItem(histKey(clientId), JSON.stringify(list.slice(0, 200))); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(HIST_EVENT, { detail: clientId }));
}
export function usePackHistory(clientId: string): PackEdit[] {
  return useSyncExternalStore(
    subHist,
    () => getPackHistory(clientId),
  );
}

/* ---- Section "done" flags (per client, per section number). ---- */
export type SectionDone = Record<number, { done: boolean; by: Role; at: string }>;
const DONE_EVENT = "geneva:packdone";
const doneKey = (clientId: string) => `pack-done-${clientId}`;
const doneCache = new Map<string, { raw: string | null; value: SectionDone }>();

export function getSectionDone(clientId: string): SectionDone {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(doneKey(clientId)); } catch { /* ignore */ }
  const c = doneCache.get(clientId);
  if (c && c.raw === raw) return c.value;
  let value: SectionDone = {};
  try { if (raw) value = JSON.parse(raw) as SectionDone; } catch { /* ignore */ }
  doneCache.set(clientId, { raw, value });
  return value;
}
function writeDone(clientId: string, next: SectionDone) {
  try { sessionStorage.setItem(doneKey(clientId), JSON.stringify(next)); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(DONE_EVENT, { detail: clientId }));
}
/** Marks a section done or reopened and records a history entry. */
export function setSectionDone(clientId: string, section: number, done: boolean, by?: Role) {
  const role = by ?? currentRole();
  writeDone(clientId, { ...getSectionDone(clientId), [section]: { done, by: role, at: new Date().toISOString() } });
  recordPackEdit(clientId, section, role, done ? "marked done" : "reopened");
}
export function useSectionDone(clientId: string): SectionDone {
  return useSyncExternalStore(
    subDone,
    () => getSectionDone(clientId),
  );
}

/** Signature per role key (rm | pm). dataUrl is a drawn/uploaded image, or empty when typed is true (name is the typed signature). */
export interface PackSignature { name: string; dataUrl: string; signedAt: string; typed?: boolean }
export type PackSignatures = Record<string, PackSignature>;
const SIG_EVENT = "geneva:packsig";
const sigKey = (clientId: string) => `pack-sig-${clientId}`;

export function loadSignatures(clientId: string): PackSignatures {
  try { const raw = sessionStorage.getItem(sigKey(clientId)); return raw ? (JSON.parse(raw) as PackSignatures) : {}; } catch { return {}; }
}
/** `sig` null removes the signature. signedAt is the upload time. */
export function saveSignature(clientId: string, role: string, sig: PackSignature | null) {
  const next = { ...loadSignatures(clientId) };
  if (sig) next[role] = sig; else delete next[role];
  try { sessionStorage.setItem(sigKey(clientId), JSON.stringify(next)); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(SIG_EVENT, { detail: clientId }));
}
export function subscribeSignatures(clientId: string, fn: (s: PackSignatures) => void): () => void {
  const on = (e: Event) => { if ((e as CustomEvent<string>).detail === clientId) fn(loadSignatures(clientId)); };
  window.addEventListener(SIG_EVENT, on);
  return () => window.removeEventListener(SIG_EVENT, on);
}

const sigCache = new Map<string, { raw: string | null; value: PackSignatures }>();
function snapSignatures(clientId: string): PackSignatures {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(sigKey(clientId)); } catch { /* ignore */ }
  const c = sigCache.get(clientId);
  if (c && c.raw === raw) return c.value;
  let value: PackSignatures = {};
  try { if (raw) value = JSON.parse(raw) as PackSignatures; } catch { /* ignore */ }
  sigCache.set(clientId, { raw, value });
  return value;
}
/** Reactive signatures for a client, keyed by role (rm | pm). */
export function useSignatures(clientId: string): PackSignatures {
  return useSyncExternalStore(
    subSig,
    () => snapSignatures(clientId),
  );
}
