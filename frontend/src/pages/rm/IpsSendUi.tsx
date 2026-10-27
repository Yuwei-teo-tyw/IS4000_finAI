import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "../../components/ui";
import type { IpsStatusLabel } from "./ipsSendUtil";

/** Explicit status badge: Draft / Sent to PM / Returned by PM. */
export function IpsStatusBadge({ status, detail }: { status: IpsStatusLabel; detail?: string }) {
  return (
    <span data-testid="ips-send-status" className="inline-flex items-center gap-2 rounded-sm border border-hairline-strong px-3 py-1 text-sm font-light text-ink">
      <span aria-hidden className={`size-2 rounded-full ${status === "Draft" ? "bg-ink-muted" : "bg-green-600"}`} />
      {status}{detail ? ` · ${detail}` : ""}
    </span>
  );
}

/** Lux modal with one primary action. */
export function ConfirmDialog({ title, children, primary, secondary, onPrimary, onSecondary, busy }: {
  title: string; children: ReactNode; primary: string; secondary: string; onPrimary: () => void; onSecondary: () => void; busy?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cancel = useRef(onSecondary);
  cancel.current = onSecondary;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") cancel.current(); };
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onSecondary(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-[560px] rounded-sm border border-hairline bg-surface-100 p-8 text-ink">
        <h2 className="text-2xl font-light">{title}</h2>
        <div className="mt-4 text-[15px] font-light leading-relaxed text-ink-700">{children}</div>
        <div className="mt-8 flex justify-end gap-3">
          <Button variant="secondary" onClick={onSecondary}>{secondary}</Button>
          <Button onClick={onPrimary} disabled={busy}>{busy ? "Working…" : primary}</Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
