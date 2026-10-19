import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import type { Role } from "../../types/arc";
import { markRead, useNotifications, type AppNotification } from "../../services/notificationStore";

const TTL = 6000;

/** Where a notification leads for the receiving role. */
export function notificationPath(role: Role, n: Pick<AppNotification, "clientId" | "kind">): string {
  if (role === "ps") return "/ps/inbox";
  if (role === "ic") return `/ic/cases/${n.clientId}/${n.kind === "ips" ? "ips" : "pack"}`;
  return `/rm/clients/${n.clientId}/${n.kind === "ips" ? "ips-creation" : "review-pack"}`;
}

/** Transient top-right pop-ups for hand-overs received by the current role. Render once, from AppShell. */
export default function NotificationToaster({ role }: { role: Role }) {
  const unread = useNotifications(role);
  const navigate = useNavigate();
  const seen = useRef<Set<string> | null>(null);
  const [toasts, setToasts] = useState<AppNotification[]>([]);

  useEffect(() => {
    if (seen.current === null) { seen.current = new Set(unread.map((n) => n.id)); return; } // existing ones show as pills, not toasts
    const fresh = unread.filter((n) => !seen.current!.has(n.id));
    if (!fresh.length) return;
    fresh.forEach((n) => seen.current!.add(n.id));
    setToasts((t) => [...fresh, ...t].slice(0, 4));
    fresh.forEach((n) => window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== n.id)), TTL));
  }, [unread]);

  useEffect(() => { setToasts((t) => t.filter((x) => x.to === role)); }, [role]);

  if (!toasts.length) return null;
  const dismiss = (id: string) => setToasts((t) => t.filter((x) => x.id !== id));
  return (
    <div className="pointer-events-none fixed right-6 top-6 z-50 flex w-[360px] max-w-[calc(100vw-3rem)] flex-col gap-3 print:hidden" role="status" aria-live="polite">
      {toasts.map((n) => (
        <div key={n.id} className="pointer-events-auto flex items-start gap-3 rounded-sm border border-hairline bg-surface-100 p-5 shadow-card">
          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { markRead(n.id); dismiss(n.id); navigate(notificationPath(role, n)); }}>
            <p className="flex items-center gap-2 text-xs text-ink-muted"><span className="size-2 rounded-full bg-brand" aria-hidden="true" />{n.kind === "ips" ? "New IPS" : "New Review pack"}</p>
            <p className="mt-2 text-sm text-ink">{n.message}</p>
          </button>
          <button type="button" aria-label="Dismiss" onClick={() => dismiss(n.id)} className="text-ink-muted hover:text-ink"><X size={16} aria-hidden="true" /></button>
        </div>
      ))}
    </div>
  );
}
