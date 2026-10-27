import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { MeetingNoteModal } from "../../geneva/MeetingNoteModal";
import { IPS_FRAME, LABEL, SMALL, SubHead, WRAP } from "./parts";
import { targetLine, type IpsTarget } from "./ipsTypes";

const fmtDate = (d?: string) => { const t = d ? new Date(d) : null; return t && !isNaN(+t) ? t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : d ?? ""; };
const FIGURE = /(?:\b(SGD|USD|HKD|EUR|GBP|CHF|S\$|US\$|\$)\s*)?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|mn|bn|[mbk])?\b/i;
const HORIZON = /\b(?:within|in|over|by)\s+(?:the\s+next\s+)?(\d+)\s+years?\b/i;

interface Parsed { figure: string; horizon: string; descriptor: string }

/** Tolerant parse: free text wins (it is what the RM edits), structured fields are the fallback. */
function parseTarget(t: IpsTarget): Parsed {
  const text = t.text?.trim() ? t.text.trim() : targetLine(t);
  let rest = text;
  let figure = "";
  const f = FIGURE.exec(rest);
  if (f) {
    const cur = f[1] ?? t.currency ?? "";
    figure = [cur.replace(/^S\$$/, "SGD").replace(/^US\$$/, "USD").replace(/^\$$/, "").toUpperCase(), `${f[2]}${f[3] ? f[3].replace(/^million$/i, "M").replace(/^billion$/i, "B").replace(/^mn$/i, "M").replace(/^bn$/i, "B").toUpperCase() : ""}`].filter(Boolean).join(" ");
    rest = rest.replace(f[0], " ");
  } else if (t.amount != null && t.amount !== "") figure = [t.currency, String(t.amount)].filter(Boolean).join(" ");
  let horizon = "";
  const h = HORIZON.exec(rest);
  if (h) { horizon = `within ${h[1]} years`; rest = rest.replace(h[0], " "); }
  else if (t.horizonYears) horizon = `within ${t.horizonYears} years`;
  rest = rest.replace(/^\s*(?:to\s+)?(?:reach|grow(?:\s+to)?|target|achieve|build(?:\s+to)?)\b\s*(?:of|to)?/i, " ").replace(/\s+/g, " ").replace(/^[\s,;:.-]+|[\s,;:.-]+$/g, "");
  return { figure, horizon, descriptor: rest };
}

const noteMeta = (n: IpsTarget["source_note"]) => (n && typeof n === "object" ? { id: n.id, date: n.date, title: n.title } : { id: undefined, date: undefined, title: n ?? undefined });
const dateOf = (t: IpsTarget) => { const d = noteMeta(t.source_note).date; return d ? +new Date(d) || 0 : 0; };

function EditableText({ value, onCommit, onCancel }: { value: string; onCommit: (v: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(value);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  const finish = (fn: () => void) => { if (done.current) return; done.current = true; fn(); };
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <input ref={ref} value={v} aria-label="Target" placeholder="e.g. SGD 800M investment portfolio within 5 years"
      className="w-full rounded-sm bg-transparent px-1 py-0.5 text-[15px] outline-none focus:ring-1 focus:ring-ink/30"
      onChange={(e) => setV(e.target.value)} onBlur={() => finish(() => onCommit(v))}
      onKeyDown={(e) => { if (e.key === "Enter") finish(() => onCommit(v)); else if (e.key === "Escape") finish(onCancel); }} />
  );
}

/** Targets list for IPS section 3: figure + descriptor + source, same rows in preview and editor. */
export function TargetsBlock({ targets, editing, onChange, clientId }: { targets: IpsTarget[]; editing?: boolean; onChange?: (t: IpsTarget[]) => void; clientId?: string }) {
  const cid = clientId ?? "";
  const [active, setActive] = useState<number | null>(null);
  const [modal, setModal] = useState<{ id: string; label?: string; date?: string } | null>(null);
  if (!editing && !targets.length) return null;
  const rows = targets.map((t, i) => ({ t, i })).sort((a, b) => dateOf(b.t) - dateOf(a.t));
  const set = (i: number, text: string) => { setActive(null); onChange?.(text.trim() ? targets.map((t, j) => (j === i ? { ...t, text } : t)) : targets.filter((t, j) => j !== i || !!targetLine(t).trim())); };
  const cancel = (i: number) => { setActive(null); if (!targetLine(targets[i]).trim()) onChange?.(targets.filter((_, j) => j !== i)); };
  return (
    <div className="avoid-break" data-testid="ips-targets">
      <SubHead>Targets</SubHead>
      <div className={`mt-2 overflow-x-auto ${IPS_FRAME}`}>
        <table className="w-full min-w-[640px] table-fixed border-collapse text-left text-[15px] leading-6">
          <colgroup><col className="w-[22%]" /><col className="w-[16%]" /><col /><col className="w-[24%]" />{editing && <col className="w-9 print:hidden" />}</colgroup>
          <thead>
            <tr className={LABEL}>
              <th scope="col" className="px-5 py-4 font-normal border-l border-hairline first:border-l-0">Target</th>
              <th scope="col" className="px-5 py-4 font-normal border-l border-hairline first:border-l-0">Horizon</th>
              <th scope="col" className="px-5 py-4 font-normal border-l border-hairline first:border-l-0">Description</th>
              <th scope="col" className="px-5 py-4 font-normal border-l border-hairline first:border-l-0">Source</th>
              {editing && <th scope="col" className="px-5 py-4 border-l border-hairline print:hidden"><span className="sr-only">Remove</span></th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ t, i }) => {
              const p = parseTarget(t);
              const m = noteMeta(t.source_note);
              const src = m.title || m.date ? ["From meeting note", m.date ? fmtDate(m.date) : m.title].join(" · ") : "";
              const open = editing && active === i;
              const trigger = { role: editing ? "button" : undefined, tabIndex: editing ? 0 : undefined, "aria-label": editing ? "Edit target" : undefined,
                className: editing ? "cursor-text rounded-sm hover:bg-surface-200/60 focus:outline-none focus:ring-1 focus:ring-ink/30" : "",
                onClick: () => editing && setActive(i),
                onKeyDown: (e: React.KeyboardEvent) => { if (editing && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setActive(i); } } };
              return (
                <tr key={t.id ?? i} className="border-t border-hairline align-top print:break-inside-avoid">
                  {open ? (
                    <td colSpan={3} className="px-5 py-4"><EditableText value={targetLine(t)} onCommit={(v) => set(i, v)} onCancel={() => cancel(i)} /></td>
                  ) : (
                    <>
                      <th scope="row" className={`px-5 py-4 text-left text-[15px] font-light ${WRAP}`}><span {...trigger}>{p.figure || (p.descriptor ? <span className="text-ink-muted">-</span> : <span className="text-ink-muted">Add a target</span>)}</span></th>
                      <td className={`border-l border-hairline px-5 py-4 ${WRAP}`}>{p.horizon || <span className="text-ink-muted">-</span>}</td>
                      <td className={`border-l border-hairline px-5 py-4 ${WRAP}`}><span {...trigger}>{p.descriptor || <span className="text-ink-muted">-</span>}</span></td>
                    </>
                  )}
                  <td className={`border-l border-hairline px-5 py-4 ${SMALL} text-ink-muted ${WRAP}`}>
                    {src ? (m.id && cid
                      ? <button type="button" className="text-left underline-offset-2 hover:text-ink hover:underline print:no-underline" onClick={() => setModal({ id: m.id!, label: m.title, date: m.date })}>{src}</button>
                      : src) : "-"}
                  </td>
                  {editing && <td className="border-l border-hairline px-3 py-4 text-right print:hidden"><button type="button" aria-label="Remove target" className="rounded-sm p-1 text-ink-muted hover:text-negative focus:outline-none focus:ring-1 focus:ring-ink/30" onClick={() => onChange?.(targets.filter((_, j) => j !== i))}><X size={14} aria-hidden /></button></td>}
                </tr>
              );
            })}
            {!rows.length && <tr className="border-t border-hairline"><td colSpan={editing ? 5 : 4} className="px-5 py-4 text-ink-muted">Not yet completed</td></tr>}
          </tbody>
        </table>
      </div>
      {editing && <button type="button" className="mt-3 text-[13px] leading-5 text-ink-muted underline-offset-2 hover:text-ink hover:underline print:hidden" onClick={() => { onChange?.([...targets, { text: "" }]); setActive(targets.length); }}>+ Add target</button>}
      {modal && cid && <MeetingNoteModal clientId={cid} noteId={modal.id} fallbackLabel={modal.label} fallbackDate={modal.date} onClose={() => setModal(null)} />}
    </div>
  );
}
