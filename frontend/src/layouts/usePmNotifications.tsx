import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAllIpsReturned, useAllIpsSent } from "../services/workflowStore";
import { useAllPackHandovers } from "../services/packHandover";
import { arcApi } from "../services/arcApi";
import { ToastStack, type ToastItem } from "../components/ui/Toast";

export interface PmPending { key: string; clientId: string; kind: "ips" | "pack" }

/** Requests waiting on the PM, from live store state (IPS sent and not returned, packs with status sent_to_pm). */
export function usePmPending(): PmPending[] {
  const sent = useAllIpsSent();
  const returned = useAllIpsReturned();
  const packs = useAllPackHandovers();
  return useMemo(() => [
    ...sent.filter((id) => !returned.includes(id)).map((id) => ({ key: `ips:${id}`, clientId: id, kind: "ips" as const })),
    ...packs.map((p) => ({ key: `pack:${p.clientId}`, clientId: p.clientId, kind: "pack" as const })),
  ], [sent, returned, packs]);
}
export const usePmPendingCount = (): number => usePmPending().length;

const SEEN_KEY = "arc.pmNotify.seen";
const BASELINE_MS = 3000; // absorb requests that load asynchronously on app start
const readSeen = (): string[] | null => { try { const v = sessionStorage.getItem(SEEN_KEY); return v ? (JSON.parse(v) as string[]) : null; } catch { return null; } };
const writeSeen = (s: Set<string>) => { try { sessionStorage.setItem(SEEN_KEY, JSON.stringify([...s])); } catch { /* ignore */ } };

/** Mount in the PM layout: toasts each request that arrives after the PM view opened. */
export function PmNotifications() {
  const pending = usePmPending();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const seen = useRef<Set<string>>(new Set(readSeen() ?? []));
  const startedAt = useRef(Date.now());
  const dismiss = useCallback((id: string) => setToasts((l) => l.filter((t) => t.id !== id)), []);

  useEffect(() => { arcApi.listClients().then((cs) => setNames(Object.fromEntries(cs.map((c) => [c.id, c.name])))).catch(() => {}); }, []);

  useEffect(() => {
    const baseline = Date.now() - startedAt.current < BASELINE_MS;
    const fresh = pending.filter((p) => !seen.current.has(p.key));
    // forget handled requests so a re-send toasts again
    const live = new Set(pending.map((p) => p.key));
    seen.current = new Set([...seen.current].filter((k) => live.has(k)));
    pending.forEach((p) => seen.current.add(p.key));
    writeSeen(seen.current);
    if (baseline || !fresh.length) return;
    setToasts((l) => [...l, ...fresh.map((p): ToastItem => {
      const name = names[p.clientId] ?? p.clientId.toUpperCase();
      return p.kind === "ips"
        ? { id: p.key, title: `New IPS SAA request: ${name}`, body: "The RM sent an IPS draft for your SAA.", to: `/pm/requests/${p.clientId}/ips`, actionLabel: "Open" }
        : { id: p.key, title: `New review pack: ${name}`, body: "The RM sent a review pack for your input.", to: `/pm/cases/${p.clientId}/review`, actionLabel: "Open" };
    })]);
  }, [pending, names]);

  return <ToastStack toasts={toasts} onDismiss={dismiss} />;
}
