import { useEffect } from "react";
import { Link } from "react-router-dom";
import { X } from "lucide-react";

export interface ToastItem { id: string; title: string; body?: string; to?: string; actionLabel?: string }

/** Lux popup bubble: hairline card, one action. Auto-dismisses after `ms` and can be closed. */
function ToastCard({ t, onDismiss, ms }: { t: ToastItem; onDismiss: (id: string) => void; ms: number }) {
  useEffect(() => {
    const h = window.setTimeout(() => onDismiss(t.id), ms);
    return () => window.clearTimeout(h);
  }, [t.id, ms, onDismiss]);
  return (
    <div role="status" className="pointer-events-auto flex w-80 items-start gap-3 rounded-sm border border-hairline bg-surface-100 p-4 shadow-overlay">
      <div className="min-w-0 flex-1">
        <p className="text-[14.5px] font-semibold leading-5 text-ink">{t.title}</p>
        {t.body && <p className="mt-1 text-[13px] leading-5 text-ink-muted">{t.body}</p>}
        {t.to && (
          <Link to={t.to} onClick={() => onDismiss(t.id)}
            className="mt-3 inline-flex min-h-9 items-center rounded-sm bg-brand px-4 text-[13.5px] font-normal text-on-brand hover:bg-brand-hover">
            {t.actionLabel ?? "Open"}
          </Link>
        )}
      </div>
      <button type="button" aria-label="Dismiss notification" onClick={() => onDismiss(t.id)} className="shrink-0 text-ink-muted hover:text-ink">
        <X size={16} strokeWidth={1.5} aria-hidden />
      </button>
    </div>
  );
}

export function ToastStack({ toasts, onDismiss, ms = 8000 }: { toasts: ToastItem[]; onDismiss: (id: string) => void; ms?: number }) {
  if (!toasts.length) return null;
  return (
    <div aria-live="polite" className="pointer-events-none fixed right-6 top-6 z-50 flex flex-col gap-3 print:hidden">
      {toasts.map((t) => <ToastCard key={t.id} t={t} onDismiss={onDismiss} ms={ms} />)}
    </div>
  );
}
