/**
 * Per-client, per-role store of research chat turns (sessionStorage + pub/sub, same pattern as workflowStore).
 * Feeds arcApi.professionalise({ chat }). Swap the bodies for a saved-state API later, keep the hooks.
 */
import { useSyncExternalStore } from "react";
import type { Role } from "../types/arc";

type Data = Record<string, string[]>;
const KEY = "wf-chat-context";
const listeners = new Set<() => void>();
let cache: { raw: string | null; value: Data } | null = null;
const EMPTY: string[] = [];

function read(): Data {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(KEY); } catch { /* ignore */ }
  if (cache && cache.raw === raw) return cache.value;
  let value: Data = {};
  try { if (raw) value = JSON.parse(raw) as Data; } catch { /* ignore */ }
  cache = { raw, value };
  return value;
}
function write(v: Data) {
  try { sessionStorage.setItem(KEY, JSON.stringify(v)); } catch { /* ignore */ }
  listeners.forEach((l) => l());
}
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
const k = (clientId: string, role: Role) => `${clientId}:${role}`;

/** Store one research chat turn (stored as "Q: ... A: ..."). */
export function appendChatContext(clientId: string, role: Role, turn: { q: string; a: string }): void {
  const d = read();
  write({ ...d, [k(clientId, role)]: [...(d[k(clientId, role)] ?? []), `Q: ${turn.q} A: ${turn.a}`] });
}
export function getChatContext(clientId: string, role: Role): string[] { return read()[k(clientId, role)] ?? EMPTY; }
export function useChatContext(clientId: string, role: Role): string[] {
  return useSyncExternalStore(subscribe, () => getChatContext(clientId, role));
}
