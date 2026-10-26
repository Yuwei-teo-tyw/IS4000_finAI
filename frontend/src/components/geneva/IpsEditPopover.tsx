import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { arcApi, ClientProfilingError } from "../../services/arcApi";
import type { ClientProfilingSource, IpsAssistResult } from "../../types/clientProfiling";
import { NoteModal, SourceRow } from "./ClientProfilingCard";

export interface PopoverTarget {
  /** IPS part being edited, or null for a general request from the toolbar. */
  part: number | null;
  /** Live Range of the highlighted text inside the part (null when there is no selection). */
  range: Range | null;
  /** Open straight into the panel (toolbar / keyboard) instead of the small icon. */
  expanded: boolean;
}
export interface EditableSection { part: number; title: string }

type Tok = { t: string; kind: "same" | "del" | "add" };
/** Small word-level diff (LCS over words and whitespace). */
function wordDiff(a: string, b: string): { old: Tok[]; neu: Tok[] } {
  const x = a.split(/(\s+)/).filter(Boolean), y = b.split(/(\s+)/).filter(Boolean);
  const dp = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--)
    dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const old: Tok[] = [], neu: Tok[] = [];
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { old.push({ t: x[i], kind: "same" }); neu.push({ t: y[j], kind: "same" }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) old.push({ t: x[i++], kind: "del" });
    else neu.push({ t: y[j++], kind: "add" });
  }
  while (i < x.length) old.push({ t: x[i++], kind: "del" });
  while (j < y.length) neu.push({ t: y[j++], kind: "add" });
  return { old, neu };
}

const STEPS = ["Reading this client's meeting notes…", "Drafting the wording…"];
const W = 420;
const ICON = 36;
const btn = "cursor-pointer rounded-sm px-3 py-1.5 text-[13px]";
const ghost = `${btn} border border-hairline-strong text-ink hover:bg-surface-300`;

const partEl = (n: number) => document.querySelector<HTMLElement>(`[data-ips-part="${n}"]`);

/** Insert text at a Range through the browser editing stack, so Ctrl/Cmd+Z undoes it like any other edit. */
function insertAt(el: HTMLElement, r: Range, str: string) {
  el.focus({ preventScroll: true });
  const sel = window.getSelection();
  sel?.removeAllRanges(); sel?.addRange(r);
  if (!document.execCommand("insertText", false, str)) {
    r.deleteContents(); r.insertNode(document.createTextNode(str));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

/** Floating Geneva helper for the live IPS editor: a small icon at the highlighted text that expands into the panel. */
/** Current body of a bullet-list region: one line per <li> (or per text line when the region is plain). */
export function readRegionText(el: HTMLElement): string {
  const lis = Array.from(el.querySelectorAll("li"));
  const raw = lis.length ? lis.map((l) => l.textContent ?? "") : el.innerText.split("\n");
  return raw.map((l) => l.replace(/^\s*(?:[-•*]\s+)/, "").trim()).filter(Boolean).join("\n");
}

export function IpsEditPopover({ clientId, target, sections, getText, onClose, onApplied }: {
  clientId: string; target: PopoverTarget; sections: EditableSection[];
  getText: (part: number) => string;
  onClose: () => void;
  /** Called after Accept/Insert with the region's new text (one line per bullet) so the host can sync its state. */
  onApplied?: (part: number, text: string) => void;
}) {
  const [open, setOpen] = useState(target.expanded);
  const [part, setPart] = useState<number | null>(target.part);
  const [input, setInput] = useState("");
  const [step, setStep] = useState<number | null>(null);
  const [result, setResult] = useState<IpsAssistResult | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<ClientProfilingSource | null>(null);
  const [pos, setPos] = useState({ left: 8, top: 8 });
  const ref = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  /* Kept apart from the live DOM selection: it collapses once focus moves into the panel. */
  const range = useRef<Range | null>(target.range ? target.range.cloneRange() : null);
  const selected = part != null && part === target.part && range.current ? range.current.toString() : "";

  const place = () => {
    const h = ref.current?.offsetHeight ?? 0, w = open ? W : ICON;
    const rr = range.current?.getBoundingClientRect();
    const anchor = rr && (rr.width || rr.height) ? rr : null;
    const ax = anchor ? anchor.right : window.innerWidth / 2 - w / 2;
    const ay = anchor ? anchor.bottom : 96;
    const left = Math.max(8, Math.min(ax - (open ? 0 : 0), window.innerWidth - w - 8));
    let top = ay + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, (anchor ? anchor.top : ay) - h - 8);
    if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
    setPos({ left, top });
  };
  useLayoutEffect(place, [open, result, error, step, note, draft === "" ? 0 : 1]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) area.current?.focus({ preventScroll: true }); }, [open]);

  const close = () => {
    const el = part != null ? partEl(part) : null;
    onClose();
    if (el && range.current) { el.focus({ preventScroll: true }); const s = window.getSelection(); s?.removeAllRanges(); s?.addRange(range.current); }
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    const down = (e: MouseEvent) => {
      const el = e.target as HTMLElement | null;
      if (ref.current?.contains(el) || el?.closest("[role=dialog]") || el?.closest("[data-ips-ask]")) return;
      onClose();
    };
    document.addEventListener("keydown", key); document.addEventListener("mousedown", down);
    return () => { document.removeEventListener("keydown", key); document.removeEventListener("mousedown", down); };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (mode: "professionalize" | "auto", message: string) => {
    if (step !== null) return;
    const title = sections.find((s) => s.part === part)?.title ?? "";
    const text = part != null ? getText(part) : "";
    setResult(null); setError(""); setStep(0);
    const timer = window.setInterval(() => setStep((s) => (s === null ? s : Math.min(s + 1, STEPS.length - 1))), 3500);
    try {
      const r = await arcApi.ipsAssist({ clientId, section: title, mode, currentText: text, selection: selected, message });
      setResult(r); setDraft(r.revised);
    } catch (e) {
      setError(e instanceof ClientProfilingError ? [e.message, ...e.details].join(" ") : "Something went wrong.");
    } finally { window.clearInterval(timer); setStep(null); }
  };
  const submit = () => { const m = input.trim(); if (m) run("auto", m); };

  const accept = () => {
    if (part == null || !result) return;
    const el = partEl(part);
    if (!el) return;
    const own = part === target.part && range.current && !range.current.collapsed;
    let r: Range, str = draft;
    if (result.kind === "retrieve") {
      r = document.createRange();
      if (own && range.current) { r.setStart(range.current.endContainer, range.current.endOffset); } else { r.selectNodeContents(el); r.collapse(false); }
      r.collapse(true);
      const before = document.createRange(); before.setStart(el, 0); before.setEnd(r.startContainer, r.startOffset);
      const after = document.createRange(); after.selectNodeContents(el); after.setStart(r.startContainer, r.startOffset);
      const b = before.toString(), a = after.toString();
      if (b && !b.endsWith("\n")) str = "\n" + str;
      if (a && !a.startsWith("\n")) str += "\n";
    } else if (result.target === "selection" && own && range.current) {
      r = range.current.cloneRange();
    } else { r = document.createRange(); r.selectNodeContents(el); }
    insertAt(el, r, str);
    onApplied?.(part, readRegionText(el));
    onClose();
  };

  const d = result?.kind !== "retrieve" && result?.status === "ok" ? wordDiff(result.original || selected || (part != null ? getText(part) : ""), draft) : null;
  const ok = result?.status === "ok" && result.kind !== "none" && !!draft.trim();
  const grow = (el: HTMLTextAreaElement) => { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 240)}px`; };

  if (!open) {
    return createPortal(
      <div ref={ref} style={{ left: pos.left, top: pos.top }} className="fixed z-50">
        <button type="button" aria-label="Ask Geneva about the selected text" title="Ask Geneva (Ctrl/Cmd+K)"
          onMouseDown={(e) => e.preventDefault()} onClick={() => setOpen(true)}
          className="flex cursor-pointer items-center justify-center rounded-sm border border-hairline-strong bg-surface-100 p-2 shadow-lg hover:bg-surface-300">
          <img src="/ubs-logo.png" alt="" className="ubs-logo h-5 w-auto" />
        </button>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <div ref={ref} role="dialog" aria-label="Ask Geneva" style={{ left: pos.left, top: pos.top, width: W }}
      className="fixed z-50 max-h-[80vh] max-w-[calc(100vw-16px)] space-y-4 overflow-y-auto rounded-sm border border-hairline-strong bg-surface-100 p-5 text-sm font-light text-ink shadow-lg">
      <div className="flex items-center justify-between gap-3">
        <img src="/ubs-logo.png" alt="Geneva" className="ubs-logo h-5 w-auto" />
        <button type="button" onClick={close} className="cursor-pointer text-xs text-ink-muted hover:text-ink">Close (Esc)</button>
      </div>
      {target.part == null && (
        <select value={part ?? ""} onChange={(e) => setPart(e.target.value === "" ? null : Number(e.target.value))} aria-label="Target section"
          className="w-full rounded-sm border border-hairline-strong bg-surface-100 px-2 py-1.5 text-sm font-light text-ink">
          <option value="">Choose a section to apply to</option>
          {sections.map((s) => <option key={s.part} value={s.part}>{s.title}</option>)}
        </select>
      )}
      {selected && <p className="line-clamp-3 border-l-2 border-brand pl-3 text-xs text-ink-muted">Selected: {selected}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={part == null || step !== null} onClick={() => run("professionalize", selected ? "Professionalise the selected text" : "Professionalise this section")}
          className={`${ghost} disabled:cursor-not-allowed disabled:opacity-40`}>Professionalise</button>
        <button type="button" disabled={part == null || step !== null} onClick={() => run("auto", "Retrieve relevant details from the meeting notes for this section")}
          className={`${ghost} disabled:cursor-not-allowed disabled:opacity-40`}>Retrieve from meeting notes</button>
      </div>
      <textarea ref={area} value={input} rows={3} onChange={(e) => { setInput(e.target.value); grow(e.currentTarget); }}
        placeholder="Ask Geneva… (Enter to send, Shift+Enter for a new line)" aria-label="Ask Geneva"
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
        className="block min-h-[5.5rem] w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-3 py-2 text-sm font-light leading-6 text-ink outline-none focus:border-ink" />

      {step !== null && (
        <ul className="space-y-1 text-[13px] text-ink-muted" aria-live="polite">
          {STEPS.slice(0, step + 1).map((s, i) => <li key={s} className={i === step ? "animate-pulse" : ""}>{s}</li>)}
        </ul>
      )}
      {error && <p className="text-negative" role="alert">{error}</p>}

      {result && !ok && <p className="whitespace-pre-wrap" role="status">{result.message}</p>}
      {result && ok && (
        <div className="space-y-4">
          {result.message && <p className="whitespace-pre-wrap text-ink-muted">{result.message}</p>}
          {d && (
            <div className="rounded-sm border border-hairline bg-surface-200 px-3 py-2">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">Original</p>
              <p className="whitespace-pre-wrap leading-6">{d.old.map((k, i) => <span key={i} className={k.kind === "del" ? "text-ink-muted line-through" : ""}>{k.t}</span>)}</p>
            </div>
          )}
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">{result.kind === "retrieve" ? "From the meeting notes (editable)" : "Proposed (editable)"}</p>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} aria-label="Proposed wording"
              className="block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-3 py-2 text-sm font-light leading-6 text-ink outline-none focus:border-ink" />
          </div>
          {result.notes.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-muted">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          <SourceRow sources={result.sources} role="rm" onOpenNote={setNote} />
          {part == null && <p className="text-xs text-ink-muted">Pick a target section to apply this.</p>}
          <div className="flex gap-2">
            <button type="button" disabled={part == null} onClick={accept} className={`${btn} bg-surface-inverse text-ink-inverse hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40`}>{result.kind === "retrieve" ? "Insert" : "Accept"}</button>
            <button type="button" onClick={close} className={ghost}>{result.kind === "retrieve" ? "Dismiss" : "Reject"}</button>
          </div>
        </div>
      )}
      {note && <NoteModal source={note} onClose={() => setNote(null)} />}
    </div>,
    document.body,
  );
}
