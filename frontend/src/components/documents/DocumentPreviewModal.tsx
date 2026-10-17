import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "../ui";
import { GenevaMark } from "./GenevaMark";

const PRINT_CSS = `@media print {
  body * { visibility: hidden; }
  .print-area, .print-area * { visibility: visible; }
  .print-area { position: absolute; left: 0; top: 0; width: 100%; }
  .print-shell, .print-scroll { position: static !important; overflow: visible !important; max-height: none !important; height: auto !important; box-shadow: none !important; }
}`;

export function DocumentPreviewModal({ title, onClose, children, withMark = false }: { title: string; onClose: () => void; children: ReactNode; withMark?: boolean }) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);

  return createPortal(
    <div
      className="print-shell no-print-bg fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <style>{PRINT_CSS}</style>
      <div role="dialog" aria-modal="true" aria-label={title} className="print-shell flex max-h-full w-full max-w-[920px] flex-col rounded-sm border border-hairline bg-surface-200">
        <div className="no-print flex items-center justify-between gap-4 border-b border-hairline px-8 py-5">
          <h2 className="text-xl font-light text-ink">{title}</h2>
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => window.print()}>Download PDF</Button>
            <button ref={closeRef} type="button" onClick={onClose} className="inline-flex min-h-9 items-center rounded-sm border border-ink bg-transparent px-4 text-[15px] font-semibold text-ink hover:bg-surface-300">Close</button>
          </div>
        </div>
        <div className="print-scroll flex-1 overflow-y-auto p-8">
          <div className="print-area">{withMark && <GenevaMark className="mb-6" />}{children}</div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
