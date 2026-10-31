import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Eye, Printer, X } from "lucide-react";
import { Button } from "../ui";
import { GeneratedPackDocument, type PackDocProps } from "./GeneratedPackDocument";

/** Large read-only preview of the review pack. Renders from the props it is given, so it always shows the live pack. */
export function PackPreviewDialog({ open, onClose, ...doc }: PackDocProps & { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && ref.current) {
        const f = Array.from(ref.current.querySelectorAll<HTMLElement>("button,[href],[tabindex]:not([tabindex='-1'])"));
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col bg-ink-900/60 print:static print:block print:bg-white" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label="Review pack preview" tabIndex={-1} className="m-4 flex min-h-0 flex-1 flex-col bg-surface-100 outline-none sm:m-8 print:m-0">
        <div className="flex items-center justify-between gap-4 border-b border-hairline bg-white px-6 py-4 print:hidden">
          <h2 className="text-xl">Review pack preview</h2>
          <div className="flex gap-3">
            <Button variant="secondary" onClick={() => window.print()}><Printer size={16} /> Print</Button>
            <Button variant="ghost" onClick={onClose}><X size={16} /> Close</Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-6 sm:p-10 print:overflow-visible print:p-0">
          <div className="mx-auto w-full max-w-[297mm] bg-white p-8 shadow-sm sm:p-14 print:max-w-none print:p-0 print:shadow-none">
            <GeneratedPackDocument {...doc} preview />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Eye-icon trigger plus dialog. Drop next to the editable pack. */
export function PackPreviewButton(doc: PackDocProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}><Eye size={16} /> Preview review pack</Button>
      <PackPreviewDialog {...doc} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
