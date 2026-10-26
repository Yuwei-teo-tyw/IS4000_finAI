import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { X } from "lucide-react";
import { MeetingNoteModal } from "../../geneva/MeetingNoteModal";
import { WRAP } from "./parts";
import { targetLine, type IpsTarget } from "./ipsTypes";

const fmtDate = (d?: string) => { const t = d ? new Date(d) : null; return t && !isNaN(+t) ? t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : d ?? ""; };
const HEADING = "text-[12px] uppercase tracking-[0.06em] text-ink-muted";
const FIGURE = /(?:\b(SGD|USD|HKD|EUR|GBP|CHF|S\$|US\$|\$)\s*)?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|mn|bn|[mbk])?\b/i;
const HORIZON = /\b(?:within|in|over|by)\s+(?:the\s+next\s+)?(\d+)\s+years?\b/i;

interface Parsed { figure: string; descriptor: string }

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
  return { figure, descriptor: [rest, horizon].filter(Boolean).join(" · ") };
}

const noteMeta = (n: IpsTarget["source_note"]) => (n && typeof n === "object" ? { id: n.id, date: n.date, title: n.title } : { id: undefined, date: undefined, title: n ?? undefined });
const dateOf = (t: IpsTarget) => { const d = noteMeta(t.source_note).date; return d ? +new Date(d) || 0 : 0; };

function EditableText({ value, onCommit, onCancel }: { value: string; onCommit: (v: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(value);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <input ref={ref} value={v} aria-label="Target" placeholder="e.g. SGD 800M investment portfolio within 5 years"
      className="w-full rounded-sm bg-transparent px-1 py-0.5 text-[16px] outline-none focus:ring-1 focus:ring-ink/30"
      onChange={(e) => setV(e.target.value)} onBlur={() => onCommit(v)}
      onKeyDown={(e) => { if (e.key === "Enter") onCommit(v); else if (e.key === "Escape") onCancel(); }} />
  );
}

/** Targets list for IPS section 3: figure + descriptor + source, same rows in preview and editor. */
export function TargetsBlock({ targets, editing, onChange, clientId }: { targets: IpsTarget[]; editing?: boolean; onChange?: (t: IpsTarget[]) => void; clientId?: string }) {
  const params = useParams();
  const cid = clientId ?? params.clientId ?? "";
  const [active, setActive] = useState<number | null>(null);
  const [modal, setModal] = useState<{ id: string; label?: string; date?: string } | null>(null);
  if (!editing && !targets.length) return null;
  const rows = targets.map((t, i) => ({ t, i })).sort((a, b) => dateOf(b.t) - dateOf(a.t));
  const set = (i: number, text: string) => { setActive(null); onChange?.(targets.map((t, j) => (j === i ? { ...t, text } : t))); };
  return (
    <div className="avoid-break mb-6 border-b border-hairline pb-4" data-testid="ips-targets">
      <p className={HEADING}>Targets</p>
      <ul className="mt-2 divide-y divide-hairline">
        {rows.map(({ t, i }) => {
          const p = parseTarget(t);
          const m = noteMeta(t.source_note);
          const src = m.title || m.date ? ["From meeting note", m.date ? fmtDate(m.date) : m.title].join(" · ") : "";
          return (
            <li key={t.id ?? i} className="group flex items-baseline gap-4 py-2.5">
              <div className={`flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5 ${WRAP}`}>
                {editing && active === i ? (
                  <EditableText value={targetLine(t)} onCommit={(v) => set(i, v)} onCancel={() => setActive(null)} />
                ) : (
                  <span role={editing ? "button" : undefined} tabIndex={editing ? 0 : undefined} aria-label={editing ? "Edit target" : undefined}
                    className={`flex flex-wrap items-baseline gap-x-3 ${editing ? "cursor-text rounded-sm hover:bg-surface-200/60 focus:outline-none focus:ring-1 focus:ring-ink/30" : ""}`}
                    onClick={() => editing && setActive(i)} onKeyDown={(e) => { if (editing && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setActive(i); } }}>
                    {p.figure && <span className="text-[18px] font-normal leading-[26px]">{p.figure}</span>}
                    <span className="text-[14px] leading-[22px]">{p.descriptor || (p.figure ? "" : "Add a target")}</span>
                  </span>
                )}
                {src && (m.id && cid
                  ? <button type="button" className="text-[12px] text-ink-muted underline-offset-2 hover:text-ink hover:underline print:no-underline" onClick={() => setModal({ id: m.id!, label: m.title, date: m.date })}>{src}</button>
                  : <span className="text-[12px] text-ink-muted">{src}</span>)}
              </div>
              {editing && <button type="button" aria-label="Remove target" className="shrink-0 rounded-sm p-1 text-ink-muted opacity-0 transition-opacity hover:text-negative focus:opacity-100 focus:outline-none focus:ring-1 focus:ring-ink/30 group-hover:opacity-100 print:hidden" onClick={() => onChange?.(targets.filter((_, j) => j !== i))}><X size={14} aria-hidden /></button>}
            </li>
          );
        })}
      </ul>
      {editing && <button type="button" className="mt-2 text-[13px] text-ink-muted hover:text-ink hover:underline print:hidden" onClick={() => { onChange?.([...targets, { text: "" }]); setActive(targets.length); }}>+ Add target</button>}
      {modal && cid && <MeetingNoteModal clientId={cid} noteId={modal.id} fallbackLabel={modal.label} fallbackDate={modal.date} onClose={() => setModal(null)} />}
    </div>
  );
}
