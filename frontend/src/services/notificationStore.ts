/** Frontend-only hand-over notifications (sessionStorage + useSyncExternalStore). Swap for a push/notification API later, keep the hooks. */
import { useSyncExternalStore } from "react";
import type { Role } from "../types/arc";
import { clients } from "../mock/data";

export type NotificationKind = "ips" | "pack";
export interface AppNotification {
  id: string; to: Role; from: Role; clientId: string; clientName: string; kind: NotificationKind; message: string; at: string; read: boolean;
}

const KEY = "wf-notifications";
const listeners = new Set<() => void>();
let cache: { raw: string | null; value: AppNotification[] } | null = null;
const byRole = new Map<Role, { src: AppNotification[]; value: AppNotification[] }>();

const read = (): AppNotification[] => {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(KEY); } catch { /* ignore */ }
  if (cache && cache.raw === raw) return cache.value;
  let value: AppNotification[] = [];
  try { if (raw) value = JSON.parse(raw) as AppNotification[]; } catch { /* ignore */ }
  cache = { raw, value };
  return value;
};
const write = (value: AppNotification[]) => {
  try { sessionStorage.setItem(KEY, JSON.stringify(value.slice(0, 100))); } catch { /* ignore */ }
  listeners.forEach((l) => l());
};
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** Client name lookup for services (pages must not import mock). */
export const clientNameOf = (clientId: string): string => clients.find((c) => c.id === clientId)?.name ?? clientId.toUpperCase();
export const PERSON: Record<Role, string> = { rm: "Isabel", ic: "Wei Lun", ps: "David" };

export function notify(n: { to: Role; clientId: string; kind: NotificationKind; from: Role; message: string }) {
  const item: AppNotification = {
    ...n, id: `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    clientName: clientNameOf(n.clientId), at: new Date().toISOString(), read: false,
  };
  write([item, ...read()]);
}

/** Unread notifications for a role, newest first. */
export function useNotifications(role: Role): AppNotification[] {
  const all = useSyncExternalStore(subscribe, read);
  const c = byRole.get(role);
  if (c && c.src === all) return c.value;
  const value = all.filter((n) => n.to === role && !n.read);
  byRole.set(role, { src: all, value });
  return value;
}
export const markRead = (id: string) => write(read().map((n) => (n.id === id ? { ...n, read: true } : n)));
export const markAllRead = (role: Role) => write(read().map((n) => (n.to === role ? { ...n, read: true } : n)));
