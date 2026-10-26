import { useState } from "react";
import { WRAP } from "./parts";
import { eventTime, eventWhen, type IpsLifeEvent } from "./ipsTypes";

const INPUT = "w-full border border-hairline-strong bg-surface-100 px-2 py-1 text-[13px] text-ink placeholder:text-ink-muted focus:border-ink focus:outline-none";
const LINK = "text-[13px] text-ink underline print:hidden";

interface FormState { id?: string; when: string; label: string; detail: string }

/** Horizontal life-event timeline: dots on a hairline, alternating above/below. Scrolls on narrow screens. RM can add/edit/remove dots when `editing`. */
export function LifeEventsTimeline({ events, editing = false, onChange }: { events: IpsLifeEvent[]; editing?: boolean; onChange?: (e: IpsLifeEvent[]) => void }) {
  const [form, setForm] = useState<FormState | null>(null);
  const sorted = [...events].sort((a, b) => eventTime(a) - eventTime(b));

  const save = () => {
    if (!form || !form.label.trim() || !form.when.trim()) return;
    const w = form.when.trim();
    const date = /^\d{4}-\d{2}-\d{2}$/.test(w) ? w : undefined;
    const year = date ? Number(w.slice(0, 4)) : Number(w.match(/\d{4}/)?.[0]) || undefined;
    if (!date && !year) return;
    const base = { label: form.label.trim(), detail: form.detail.trim() || undefined, date, year };
    onChange?.(form.id
      ? events.map((e) => (e.id === form.id ? { ...e, ...base } : e))
      : [...events, { id: `manual-${Date.now()}`, ...base, manual: true }]);
    setForm(null);
  };

  return (
    <div data-testid="life-events">
      {sorted.length === 0 ? <p className="text-ink-muted">No life events recorded.</p> : (
        <div className="overflow-x-auto pb-2 print:overflow-visible">
          <ol className="relative flex min-w-max items-stretch print:min-w-0 print:flex-wrap" aria-label="Life events timeline">
            {sorted.map((e, i) => {
              const up = i % 2 === 0;
              const text = (
                <div className={`w-44 px-2 ${up ? "pb-3 text-center" : "pt-3 text-center"}`}>
                  <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{eventWhen(e)}</p>
                  <p className={`${WRAP} font-semibold`}>{e.label}</p>
                  {e.detail && <p className={`${WRAP} text-[13px] text-ink-muted`}>{e.detail}</p>}
                  {e.manual && <p className="text-[11px] uppercase tracking-[0.06em] text-ink-muted" data-testid="manual-flag">Added by RM</p>}
                  {editing && (
                    <p className="mt-1 flex justify-center gap-3 print:hidden">
                      <button type="button" className={LINK} onClick={() => setForm({ id: e.id, when: e.date ?? String(e.year ?? ""), label: e.label, detail: e.detail ?? "" })}>Edit</button>
                      <button type="button" className={LINK} onClick={() => onChange?.(events.filter((x) => x.id !== e.id))}>Remove</button>
                    </p>
                  )}
                </div>
              );
              return (
                <li key={e.id} className="avoid-break relative flex w-44 shrink-0 flex-col" data-testid="life-event">
                  <div className="flex min-h-[110px] items-end justify-center">{up && text}</div>
                  <div className="relative h-4">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-hairline-strong" aria-hidden="true" />
                    <i className={`absolute left-1/2 top-1/2 h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border ${e.manual ? "border-ink bg-surface-100" : "border-ink bg-ink"}`} />
                  </div>
                  <div className="flex min-h-[110px] items-start justify-center">{!up && text}</div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
      {editing && !form && <button type="button" className={`${LINK} mt-3`} onClick={() => setForm({ when: "", label: "", detail: "" })}>Add life event</button>}
      {editing && form && (
        <div className="mt-4 grid grid-cols-1 gap-3 border border-hairline p-4 sm:grid-cols-[160px_1fr_1fr] print:hidden" role="group" aria-label="Life event">
          <label className="text-[12px] text-ink-muted">Date or year
            <input className={INPUT} value={form.when} placeholder="2031 or 2031-06-30" onChange={(e) => setForm({ ...form, when: e.target.value })} />
          </label>
          <label className="text-[12px] text-ink-muted">Event
            <input className={INPUT} value={form.label} placeholder="e.g. Retirement" onChange={(e) => setForm({ ...form, label: e.target.value })} />
          </label>
          <label className="text-[12px] text-ink-muted">Detail (optional)
            <input className={INPUT} value={form.detail} onChange={(e) => setForm({ ...form, detail: e.target.value })} />
          </label>
          <div className="flex gap-4 sm:col-span-3">
            <button type="button" className={LINK} onClick={save}>{form.id ? "Update event" : "Add event"}</button>
            <button type="button" className={`${LINK} text-ink-muted`} onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
