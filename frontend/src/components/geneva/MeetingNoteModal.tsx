import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import type { MeetingNote } from "../../types/arc";

const fmtDate = (d?: string) => { const t = d ? new Date(d) : null; return t && !isNaN(+t) ? t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : d ?? ""; };
const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

/** Splits a paragraph around the cited passage (whitespace-insensitive) so it can be highlighted. */
function withMark(p: string, passage?: string): ReactNode {
  const q = passage?.trim();
  if (!q) return p;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+"), "i");
  const m = re.exec(p);
  if (!m) return p;
  return <>{p.slice(0, m.index)}<mark data-cited className="bg-surface-300 px-0.5 text-ink">{m[0]}</mark>{p.slice(m.index + m[0].length)}</>;
}

/** Centred modal with the original meeting note; opened from a note citation in Geneva. Esc, X and backdrop close it. */
export function MeetingNoteModal({ clientId, noteId, passage, fallbackLabel, fallbackDate, onClose }: { clientId: string; noteId: string; passage?: string; fallbackLabel?: string; fallbackDate?: string; onClose: () => void }) {
  const [note, setNote] = useState<MeetingNote | null | undefined>(undefined);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    let live = true;
    arcApi.getMeetingNotes(clientId).then((ns) => live && setNote(ns.find((n) => n.id === noteId) ?? null), () => live && setNote(null));
    return () => { live = false; };
  }, [clientId, noteId]);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onCloseRef.current(); return; }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const f = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button, [href], [tabindex]:not([tabindex='-1'])"));
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); document.body.style.overflow = prev; opener?.focus?.(); };
  }, []);

  useEffect(() => { if (note) dialogRef.current?.querySelector("[data-cited]")?.scrollIntoView({ block: "center" }); }, [note]);

  const title = note?.title ?? fallbackLabel ?? "Meeting note";
  const paras = note ? note.originalText.split(/\n\s*\n/) : [];
  const found = !!passage && paras.some((p) => norm(p).includes(norm(passage)));
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title} className="flex max-h-full w-full max-w-[760px] flex-col rounded-sm border border-hairline bg-surface-100 text-ink">
        <div className="flex items-start justify-between gap-4 border-b border-hairline px-8 py-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Meeting note</p>
            <h2 className="mt-2 text-2xl font-light">{title}</h2>
            {(note?.date ?? fallbackDate) && <p className="mt-1 text-sm text-ink-muted">{fmtDate(note?.date ?? fallbackDate)}</p>}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border border-hairline-strong text-ink hover:bg-surface-300"><X size={18} strokeWidth={1.5} /></button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-8 py-6">
          {note === undefined && <p className="text-base text-ink-muted">Loading…</p>}
          {note === null && (
            <div role="status">
              <p className="text-lg font-light">Note not found</p>
              <p className="mt-2 text-base leading-relaxed text-ink-700">This meeting note is not available in this workspace.</p>
              {passage && <p className="mt-6 border-l-2 border-ink-muted pl-4 text-sm italic text-ink-700">Cited passage: {passage}</p>}
            </div>
          )}
          {paras.map((p, i) => <p key={i} className="text-base leading-relaxed text-ink">{withMark(p, passage)}</p>)}
          {note && passage && !found && <p className="border-l-2 border-ink-muted pl-4 text-sm italic text-ink-700">Cited passage: {passage}</p>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
