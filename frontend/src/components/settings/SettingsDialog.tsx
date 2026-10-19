import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Terminal, X } from "lucide-react";
import type { Role } from "../../types/arc";
import { Button } from "../ui";

const key = (role: Role) => `arc.systemPrompt.${role}`;

export function loadSystemPrompt(role: Role): string {
  try { return localStorage.getItem(key(role)) ?? ""; } catch { return ""; }
}

const HINTS: Record<Role, string> = {
  rm: "e.g. Keep summaries short. Always list follow-ups for the client meeting.",
  ic: "e.g. Explain allocation changes in plain words and cite the CIO view.",
  ps: "e.g. Prefer low-fee funds. Flag any product above the client's risk limit.",
};

/** Sidebar-bottom settings: saves the user's standing instructions for Geneva (frontend only, stored in this browser). */
export default function SettingsDialog({ role }: { role: Role }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;
    setText(loadSystemPrompt(role));
    setSaved(false);
    areaRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, role]);

  const save = () => {
    try { localStorage.setItem(key(role), text.trim()); } catch { /* ignore */ }
    setSaved(true);
  };

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-label="System prompt" title="System prompt"
        className="flex min-h-10 w-full items-center gap-3 rounded-sm border border-hairline px-3 text-[13.5px] text-ink hover:bg-surface-300 max-md:justify-center max-md:px-0">
        <Terminal size={16} strokeWidth={1.5} aria-hidden />
        <span className="max-md:sr-only">System prompt</span>
      </button>
      {open && createPortal(
        <div className="no-print fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
          <div role="dialog" aria-modal="true" aria-label="System prompt" className="animate-geneva-in w-full max-w-xl rounded-sm border border-hairline bg-surface-100 p-10">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-2xl font-light">System prompt</h2>
                <p className="mt-2 text-base font-light text-ink-700">Standing instructions for Geneva. They are saved in this browser for your current role.</p>
              </div>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close system prompt" className="p-1 text-ink-muted hover:text-ink"><X size={20} /></button>
            </div>
            <label htmlFor="system-prompt" className="mt-8 block text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">System prompt</label>
            <textarea id="system-prompt" ref={areaRef} value={text} onChange={(e) => { setText(e.target.value); setSaved(false); }} rows={7} placeholder={HINTS[role]}
              className="mt-3 block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 p-4 text-[15px] font-light leading-6 text-ink placeholder:text-ink-muted" />
            <div className="mt-8 flex flex-wrap items-center justify-end gap-3">
              {saved && <span role="status" className="mr-auto text-sm text-ink-muted">Saved</span>}
              <Button variant="secondary" onClick={() => { setText(""); setSaved(false); }}>Clear</Button>
              <Button variant="primary" onClick={save}>Save</Button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
