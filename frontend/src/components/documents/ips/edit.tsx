import { useEffect, useLayoutEffect, useRef } from "react";
import type { Bucket3L } from "../../../types/arc";
import { sgd } from "../../ui";
import { WRAP, EDIT_BOX, EditField } from "./parts";
import { BUCKET_BG, BUCKET_VAR } from "./charts";

/* ---------- Word-like bullet editor (contentEditable ul/li) ---------- */

const lisOf = (ul: HTMLElement) => Array.from(ul.children).filter((c): c is HTMLLIElement => c.tagName === "LI");
const serialize = (ul: HTMLElement) => lisOf(ul).map((li) => (li.textContent ?? "").replace(/\s*\n\s*/g, " ")).join("\n");

function focusEnd(li: HTMLElement, atStart = false) {
  const r = document.createRange();
  r.selectNodeContents(li);
  r.collapse(atStart);
  const s = window.getSelection();
  s?.removeAllRanges();
  s?.addRange(r);
}

function currentLi(ul: HTMLElement): HTMLLIElement | null {
  const n = window.getSelection()?.anchorNode;
  const el = n instanceof Element ? n : n?.parentElement;
  const li = el?.closest("li") ?? null;
  return li && li.parentElement === ul ? (li as HTMLLIElement) : null;
}

const PLACEHOLDER = "empty:before:text-ink-muted empty:before:content-[attr(data-placeholder)]";

export function BulletEditor({ part, value, onChange, label, placeholder = "Add a bullet…" }: {
  part?: number; value: string; onChange: (v: string) => void; label: string; placeholder?: string;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const built = useRef(false);

  // Sync DOM from props only when it differs from what the DOM already says (external replace, e.g. Geneva).
  useLayoutEffect(() => {
    const ul = ref.current;
    if (!ul) return;
    if (built.current && serialize(ul) === value) return;
    built.current = true;
    ul.replaceChildren(...(value === "" ? [""] : value.split("\n")).map((t) => {
      const li = document.createElement("li");
      li.className = `${WRAP} ${PLACEHOLDER}`;
      li.dataset.placeholder = placeholder;
      li.textContent = t;
      return li;
    }));
  }, [value, placeholder]);

  const emit = () => { if (ref.current) onChange(serialize(ref.current)); };
  const newLi = () => {
    const li = document.createElement("li");
    li.className = `${WRAP} ${PLACEHOLDER}`;
    li.dataset.placeholder = placeholder;
    return li;
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    const ul = ref.current;
    if (!ul) return;
    const li = currentLi(ul);
    if (e.key === "Enter") {
      e.preventDefault();
      if (!li) return;
      const sel = window.getSelection();
      const next = newLi();
      if (sel && sel.rangeCount) {
        const r = sel.getRangeAt(0);
        r.deleteContents();
        const tail = document.createRange();
        tail.selectNodeContents(li);
        tail.setStart(r.endContainer, r.endOffset);
        next.appendChild(tail.extractContents());
      }
      li.after(next);
      focusEnd(next, true);
      emit();
    } else if (e.key === "Backspace" && li && (li.textContent ?? "") === "") {
      e.preventDefault();
      const items = lisOf(ul);
      if (items.length <= 1) return;
      const prev = li.previousElementSibling as HTMLElement | null;
      const nxt = li.nextElementSibling as HTMLElement | null;
      li.remove();
      if (prev) focusEnd(prev); else if (nxt) focusEnd(nxt, true);
      emit();
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLUListElement>) => {
    e.preventDefault();
    const ul = ref.current;
    const lines = e.clipboardData.getData("text/plain").split(/\r?\n/).map((l) => l.replace(/^\s*[•\-*]\s*/, "").trim()).filter(Boolean);
    if (!ul || !lines.length) return;
    document.execCommand("insertText", false, lines[0]);
    let anchor = currentLi(ul);
    for (const l of lines.slice(1)) {
      const li = newLi();
      li.textContent = l;
      anchor?.after(li);
      anchor = li;
    }
    if (anchor && lines.length > 1) focusEnd(anchor);
    emit();
  };

  return (
    <EditField>
    <ul
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="true"
      aria-label={label}
      data-ips-part={part}
      onInput={emit}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      className={`list-disc space-y-1 py-2 pl-7 pr-3 min-h-[44px] ${EDIT_BOX} print:pl-5`}
    />
    </EditField>
  );
}

/* ---------- 3L bucket editor ---------- */

export function BucketEditor({ buckets, onChange }: { buckets: Bucket3L[]; onChange: (b: Bucket3L[]) => void }) {
  const total = buckets.reduce((s, b) => s + b.pct, 0);
  const amount = buckets.reduce((s, b) => s + b.amountSgd, 0);
  const portfolio = useRef(amount);
  useEffect(() => { if (total > 0 && amount > 0) portfolio.current = (amount * 100) / total; }, [amount, total]);

  const set = (id: Bucket3L["id"], raw: string) => {
    const pct = Math.min(100, Math.max(0, Number.isFinite(Number(raw)) ? Number(raw) : 0));
    onChange(buckets.map((b) => (b.id === id ? { ...b, pct, amountSgd: Math.round((portfolio.current * pct) / 100) } : b)));
  };
  const ok = Math.abs(total - 100) < 0.005;

  return (
    <div>
      <div className="flex h-6 w-full overflow-hidden border border-hairline" role="img" aria-label="3L bucket allocation">
        {buckets.map((b) => <div key={b.id} className={BUCKET_BG[b.id]} style={{ width: `${Math.min(100, b.pct)}%` }} />)}
      </div>
      <table className="mt-4 w-full table-fixed border-collapse text-left text-[14px]">
        <thead>
          <tr className="border-b border-hairline text-[12px] uppercase tracking-[0.06em] text-ink-muted">
            <th className="py-2 pr-2 font-normal">Bucket</th><th className="py-2 pr-2 font-normal">Horizon</th>
            <th className="py-2 pr-2 text-right font-normal">Amount (SGD)</th><th className="w-24 py-2 text-right font-normal">%</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.id} className="border-b border-hairline align-middle">
              <td className="break-words py-2 pr-2"><i className={`mr-2 inline-block h-3 w-3 ${BUCKET_BG[b.id]}`} />{b.name}</td>
              <td className="break-words py-2 pr-2">{b.horizon}</td>
              <td className="py-2 pr-2 text-right">{sgd(b.amountSgd)}</td>
              <td className="py-1 text-right">
                <input
                  type="number" min={0} max={100} step={1} value={b.pct}
                  aria-label={`${b.name} percentage`}
                  onChange={(e) => set(b.id, e.target.value)}
                  className={`w-20 px-2 py-1 text-right text-[14px] text-ink ${EDIT_BOX}`}
                />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3} className="py-2 pr-2 text-right text-[12px] uppercase tracking-[0.06em] text-ink-muted">Total</td>
            <td className={`py-2 text-right ${ok ? "text-ink" : "text-negative"}`}>{total}%</td>
          </tr>
        </tfoot>
      </table>
      {!ok && (
        <p role="alert" className="mt-2 border-l-2 border-negative pl-3 text-[13px] text-negative">
          Buckets total {total}%, not 100%. {total < 100 ? `${100 - total}% is unallocated.` : `${total - 100}% over-allocated.`} Adjust the figures before issuing.
        </p>
      )}
    </div>
  );
}

/* ---------- Placeholder pie driven by 3L percentages ---------- */

export function BucketPie({ buckets }: { buckets: Bucket3L[] }) {
  const sum = buckets.reduce((s, b) => s + Math.max(0, b.pct), 0);
  const denom = Math.max(sum, 100);
  const r = 50, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="space-y-4">
      <svg viewBox="0 0 200 200" className="h-[200px] w-[200px]" role="img" aria-label="Placeholder pie of 3L buckets">
        <g transform="rotate(-90 100 100)">
          <circle cx="100" cy="100" r={r} fill="none" stroke="var(--scale-track)" strokeWidth="100" />
          {buckets.filter((b) => b.pct > 0).map((b) => {
            const len = (Math.max(0, b.pct) / denom) * c;
            const el = <circle key={b.id} cx="100" cy="100" r={r} fill="none" stroke={BUCKET_VAR[b.id]} strokeWidth="100" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} />;
            offset += len;
            return el;
          })}
        </g>
      </svg>
      <ul className="space-y-1 text-[13px]">
        {buckets.map((b) => (
          <li key={b.id} className="flex items-center gap-2"><i className="inline-block h-3 w-3" style={{ background: BUCKET_VAR[b.id] }} />{b.name}<span className="ml-auto">{b.pct}%</span></li>
        ))}
      </ul>
      <p className="text-[12px] text-ink-muted">Placeholder: driven by the 3L percentages above.</p>
    </div>
  );
}
