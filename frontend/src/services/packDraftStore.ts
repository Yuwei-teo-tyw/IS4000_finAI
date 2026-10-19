/** Frontend-only store for review-pack section text the RM wrote or applied from Geneva. Same seam style as arcApi: swap for a saved draft API later. */
const EVENT = "geneva:packdraft";
const key = (clientId: string) => `pack-draft-${clientId}`;

/** Storage key for the IPS-creation workflow, kept apart from the review pack of the same client. */
export const ipsKey = (clientId: string) => `${clientId}:ips`;

export type PackDrafts = Record<number, string>;

export function loadPackDrafts(clientId: string): PackDrafts {
  try { const raw = sessionStorage.getItem(key(clientId)); return raw ? (JSON.parse(raw) as PackDrafts) : {}; } catch { return {}; }
}

export function savePackDraft(clientId: string, section: number, text: string) {
  try { sessionStorage.setItem(key(clientId), JSON.stringify({ ...loadPackDrafts(clientId), [section]: text })); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: clientId }));
}

export function subscribePackDrafts(clientId: string, fn: (d: PackDrafts) => void): () => void {
  const on = (e: Event) => { if ((e as CustomEvent<string>).detail === clientId) fn(loadPackDrafts(clientId)); };
  window.addEventListener(EVENT, on);
  return () => window.removeEventListener(EVENT, on);
}

export interface PackSignature { name: string; dataUrl: string; signedAt: string }
export type PackSignatures = Record<string, PackSignature>;
const SIG_EVENT = "geneva:packsig";
const sigKey = (clientId: string) => `pack-sig-${clientId}`;

const mark = (t: string) => `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="160" height="60"><text x="8" y="40" font-family="cursive" font-size="28" fill="#1c1c1c">${t}</text></svg>`)}`;
/** Tan Su Shan's pack is already signed by PS and IC; only the RM's signature and completion remain. */
const SEED_SIGS: Record<string, PackSignatures> = {
  tss: {
    ps: { name: "david.svg", dataUrl: mark("David"), signedAt: "2026-10-15T15:00:00.000Z" },
    ic: { name: "weilun.svg", dataUrl: mark("Wei Lun"), signedAt: "2026-10-17T10:00:00.000Z" },
  },
};
export function loadSignatures(clientId: string): PackSignatures {
  try { const raw = sessionStorage.getItem(sigKey(clientId)); if (raw) return JSON.parse(raw) as PackSignatures; } catch { /* fall through */ }
  return SEED_SIGS[clientId] ?? {};
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
