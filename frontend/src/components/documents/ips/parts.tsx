import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { toBulletItems } from "../../../utils/bullets";

export const WRAP = "break-words [overflow-wrap:anywhere] min-w-0";

/** Split a body into bullet items (alias of the shared normaliser, document style). */
export const toBullets = (text: string): string[] => toBulletItems(text, { splitSemicolon: true, stripPeriod: true });

/** Shared edit-mode affordance: dashed hairline box, tinted fill, hover + strong focus ring. Hidden in print. */
export const EDIT_BOX =
  "rounded-sm border border-dashed border-hairline-strong bg-surface-200/50 cursor-text transition-colors " +
  "hover:border-solid hover:bg-surface-200 focus:border-solid focus:border-ink focus:bg-surface-100 " +
  "focus:outline-none focus:ring-2 focus:ring-ink/30 print:border-0 print:bg-transparent print:ring-0";

export function PencilIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden="true">
      <path d="M2 14l1-3.5L11.5 2 14 4.5 5.5 13z" /><path d="M10 3.5l2.5 2.5" />
    </svg>
  );
}

/** Wraps an editable control; shows a tiny "Editable" tag at the corner on hover/focus (edit mode only). */
export function EditField({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`group/edit relative block ${className}`}>
      {children}
      <span className="pointer-events-none absolute -top-2 right-1 flex items-center gap-1 border border-hairline bg-surface-100 px-1 text-[10px] uppercase leading-4 tracking-[0.06em] text-ink-muted opacity-0 transition-opacity group-hover/edit:opacity-100 group-focus-within/edit:opacity-100 print:hidden">
        <PencilIcon />Editable
      </span>
    </span>
  );
}

/** Locked (IC-filled) marker: muted, no border, lock icon. */
export function LockedTag({ children = "Locked" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-[0.06em] text-ink-muted print:hidden">
      <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden="true">
        <rect x="3" y="7" width="10" height="7" /><path d="M5 7V5a3 3 0 016 0v2" />
      </svg>{children}
    </span>
  );
}

export function EditLegend() {
  return (
    <p className="mt-6 flex items-center gap-2 border border-hairline bg-surface-200/50 px-3 py-2 text-[12px] text-ink-muted print:hidden">
      <PencilIcon />Fields outlined with a dashed border are editable. Locked sections are filled by the Investment Counsellor.
    </p>
  );
}

export function DocSection({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="avoid-break mt-10 min-w-0">
      <h2 className="border-b border-hairline pb-2 text-[16px] font-semibold text-ink">{n}. {title}</h2>
      <div className={`mt-4 text-[14px] leading-[22px] ${WRAP}`}>{children}</div>
    </section>
  );
}

export function Bullets({ items }: { items: string[] }) {
  return <ul className="list-disc space-y-1 pl-5">{items.map((t, i) => <li key={i} className={WRAP}>{t}</li>)}</ul>;
}

/** Single-line in-place text styled as document text (contentEditable), subtle hover/focus affordance. */
export function InlineText({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && el.textContent !== value) el.textContent = value;
  }, [value]);
  return (
    <EditField>
    <span
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-label={label}
      onInput={(e) => onChange((e.currentTarget.textContent ?? "").replace(/\s*\n\s*/g, " "))}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLElement).blur(); } }}
      onPaste={(e) => { e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain").replace(/\s*\n\s*/g, " ")); }}
      data-placeholder="Add a value…"
      className={`block min-h-[28px] px-2 py-0.5 empty:before:text-ink-muted empty:before:content-[attr(data-placeholder)] ${EDIT_BOX} print:m-0 print:p-0`}
    />
    </EditField>
  );
}

/** Rows are [label, value]. When `onEdit` is given, labels not in `locked` are editable in place. */
export function KV({ rows, onEdit, locked = [] }: {
  rows: readonly (readonly [string, string])[]; onEdit?: (label: string, v: string) => void; locked?: readonly string[];
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2">
      {rows.map(([k, v]) => (
        <div key={k} className="avoid-break min-w-0 border-b border-hairline pb-2">
          <dt className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{k}</dt>
          <dd className={`mt-0.5 ${WRAP}`}>
            {onEdit && !locked.includes(k)
              ? <InlineText value={v} label={k} onChange={(t) => onEdit(k, t)} />
              : onEdit ? <span className="inline-flex items-center gap-2 text-ink-muted">{v}<LockedTag /></span> : v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Dashes({ value, max = 5 }: { value: number; max?: number }) {
  return (
    <span className="inline-flex items-center gap-3" role="img" aria-label={`${value} of ${max}`}>
      <span className="flex gap-1" aria-hidden="true">
        {Array.from({ length: max }, (_, i) => <span key={i} className={`h-[3px] w-6 ${i < value ? "bg-brand" : "bg-scale-track"}`} />)}
      </span>
      <span>{value} of {max}</span>
    </span>
  );
}

const MAX_SIG = 1024 * 1024;

export function SignatureBlock({ label, image, editable = false, onChange }: {
  label: string; image?: string; editable?: boolean; onChange?: (dataUrl?: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState("");
  const pick = (f?: File) => {
    if (!f) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) { setErr("Use a PNG or JPEG image."); return; }
    if (f.size > MAX_SIG) { setErr("Image must be 1 MB or smaller."); return; }
    setErr("");
    const r = new FileReader();
    r.onload = () => onChange?.(String(r.result));
    r.readAsDataURL(f);
  };
  const btn = `px-3 py-1 text-[13px] text-ink ${EDIT_BOX} !cursor-pointer`;
  return (
    <div className="avoid-break min-w-0">
      <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{label}</p>
      <div className={`flex h-16 items-end border-b border-ink ${editable ? "bg-surface-200/50 print:bg-transparent" : ""}`}>
        {editable && !image && <span className="pb-1 pl-2 text-[12px] text-ink-muted print:hidden">No signature uploaded</span>}
        {image && <img src={image} alt={`${label} signature`} className="max-h-14 max-w-full object-contain" />}
      </div>
      <p className="mt-1 text-[12px] text-ink-muted">Signature</p>
      {editable && (
        <div className="mt-2 flex flex-wrap items-center gap-4 print:hidden">
          <input ref={input} type="file" accept="image/png,image/jpeg" className="sr-only" aria-label={`Upload ${label} signature`}
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          <button type="button" className={btn} onClick={() => input.current?.click()}>{image ? "Replace" : "Upload signature"}</button>
          {image && <button type="button" className={btn} onClick={() => onChange?.(undefined)}>Remove</button>}
          {err && <span role="alert" className="text-[12px] text-negative">{err}</span>}
        </div>
      )}
      <p className="mt-6">Date: ____________</p>
    </div>
  );
}
