import { useEffect, useState } from "react";
import { arcApi } from "./arcApi";

/** One "the PM returned the IPS" notice per send cycle: a re-send gives a new sentAt, so it notifies again. */
export const returnedNoticeKey = (clientId: string, sentVersion: number | null, sentAt: string | null): string => `${clientId}:${sentVersion ?? ""}:${sentAt ?? ""}`;

const STORE = "arc.ipsReturnedNotice";
type Kind = "toast" | "tab" | "book";
const read = (): Record<string, Kind[]> => { try { return JSON.parse(localStorage.getItem(STORE) ?? "{}") as Record<string, Kind[]>; } catch { return {}; } };
const listeners = new Set<() => void>();
export const isNoticeSeen = (key: string, kind: Kind): boolean => !!read()[key]?.includes(kind);
export const markNoticeSeen = (key: string, kind: Kind): void => {
  const all = read();
  if (all[key]?.includes(kind)) return;
  all[key] = [...(all[key] ?? []), kind];
  try { localStorage.setItem(STORE, JSON.stringify(all)); } catch { /* ignore */ }
  listeners.forEach((l) => l());
};

/** The current send cycle's key while the PM has returned the IPS and the RM has not yet seen the popup of this `kind`; else null. */
export function usePendingReturnedNotice(clientId: string, kind: Kind): { key: string; version: number | null; dismiss: () => void } | null {
  const [n, setN] = useState(0);
  const [cur, setCur] = useState<{ key: string; version: number | null } | null>(null);
  useEffect(() => {
    const bump = () => setN((x) => x + 1);
    listeners.add(bump);
    return () => { listeners.delete(bump); };
  }, []);
  useEffect(() => {
    let alive = true;
    const load = () => arcApi.getIpsSendStatus(clientId)
      .then((s) => { if (alive) setCur(s.status === "Returned by PM" ? { key: returnedNoticeKey(clientId, s.sentVersion, s.sentAt), version: s.sentVersion } : null); })
      .catch(() => { if (alive) setCur(null); });
    void load();
    const h = window.setInterval(load, 10_000);
    return () => { alive = false; window.clearInterval(h); };
  }, [clientId]);
  void n;
  if (!cur || isNoticeSeen(cur.key, kind)) return null;
  return { ...cur, dismiss: () => markNoticeSeen(cur.key, kind) };
}

export type ReturnedNotice = { clientId: string; key: string; popupPending: boolean };

/** Returned-IPS notices for the given clients (Client Book). An entry stays until the RM has seen the IPS-tab notice; `popupPending` is until the book popup is dismissed/opened. */
export function useReturnedNotices(clientIds: string[]): ReturnedNotice[] {
  const [n, setN] = useState(0);
  const [found, setFound] = useState<{ clientId: string; key: string }[]>([]);
  const idsKey = clientIds.join("|");
  useEffect(() => {
    const bump = () => setN((x) => x + 1);
    listeners.add(bump);
    return () => { listeners.delete(bump); };
  }, []);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      const out: { clientId: string; key: string }[] = [];
      for (const id of idsKey ? idsKey.split("|") : []) {
        try {
          const s = await arcApi.getIpsSendStatus(id);
          if (s.status === "Returned by PM") out.push({ clientId: id, key: returnedNoticeKey(id, s.sentVersion, s.sentAt) });
        } catch { /* skip */ }
      }
      if (alive) setFound(out);
    };
    void load();
    const h = window.setInterval(load, 10_000);
    return () => { alive = false; window.clearInterval(h); };
  }, [idsKey]);
  void n;
  return found.filter((f) => !isNoticeSeen(f.key, "tab")).map((f) => ({ ...f, popupPending: !isNoticeSeen(f.key, "book") }));
}
