import { useLayoutEffect, useRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { toBulletItems } from "../../../utils/bullets";

/**
 * IPS type scale (single source of truth): title 34 > HEADING (section h2) 24 > BODY 15 > SMALL 13 > LABEL 15 uppercase.
 * Body text must never exceed the section headings.
 */
export const HEADING = "text-[24px] font-light leading-8 text-ink";
export const BODY = "text-[15px] leading-6";
export const SMALL = "text-[13px] leading-5";
export const LABEL = "text-[15px] leading-5 uppercase tracking-[0.06em] font-normal text-ink-muted";
/** Shared frame + cell pattern: every IPS block (fields, goals, tables, bucket cards) uses these. */
export const IPS_FRAME = "border border-hairline";
export const CELL = "avoid-break min-w-0 px-5 py-4";
/** Sub-heading inside a section (group titles, bucket titles, table captions): same style as LABEL. */
export const SUBHEAD = LABEL;
export function SubHead({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <h3 className={`${LABEL} ${className}`}>{children}</h3>;
}

/** Framed two-column grid (one column in narrow containers). Cells draw their own top/left hairlines; the frame clips the outer ones. */
export function IpsGrid({ children, as: Tag = "div", className = "", ...rest }: { children: ReactNode; as?: "div" | "dl"; className?: string } & HTMLAttributes<HTMLElement>) {
  return (
    <div className={`@container min-w-0 ${className}`} {...rest}>
      <div className={`overflow-hidden ${IPS_FRAME}`}>
        <Tag className="-ml-px -mt-px grid min-w-0 grid-cols-1 @xl:grid-cols-2">{children}</Tag>
      </div>
    </div>
  );
}
/** One grid cell. `wide` spans both columns. */
export function Cell({ children, wide = false, as: Tag = "div", className = "", ...rest }: { children: ReactNode; wide?: boolean; as?: "div" | "section"; className?: string } & HTMLAttributes<HTMLElement>) {
  return <Tag className={`${CELL} border-l border-t border-hairline ${wide ? "@xl:col-span-2" : ""} ${className}`} {...rest}>{children}</Tag>;
}
/** Label above value cell (dt/dd). Pass `hint` for a small note under the value. */
export function Field({ label, children, hint, wide = false }: { label: string; children: ReactNode; hint?: string; wide?: boolean }) {
  return (
    <Cell wide={wide}>
      <dt className={LABEL}>{label}</dt>
      <dd className={`mt-1 ${WRAP}`}>{children}{hint && <p className={`${SMALL} mt-1 text-ink-muted`}>{hint}</p>}</dd>
    </Cell>
  );
}
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
export function EditField({ children, className = "", inline = false }: { children: ReactNode; className?: string; inline?: boolean }) {
  return (
    <span className={`group/edit relative ${inline ? "inline-block align-baseline" : "block"} ${className}`}>
      {children}
      <span className="pointer-events-none absolute -top-2 right-1 flex items-center gap-1 border border-hairline bg-surface-100 px-1 text-[12px] uppercase leading-4 tracking-[0.06em] text-ink-muted opacity-0 transition-opacity group-hover/edit:opacity-100 group-focus-within/edit:opacity-100 print:hidden">
        <PencilIcon />Editable
      </span>
    </span>
  );
}

/** Locked (IC-filled) marker: muted, no border, lock icon. */
export function LockedTag({ children = "Locked" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] uppercase tracking-[0.06em] text-ink-muted print:hidden">
      <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden="true">
        <rect x="3" y="7" width="10" height="7" /><path d="M5 7V5a3 3 0 016 0v2" />
      </svg>{children}
    </span>
  );
}

export function DocSection({ n, title, children, locked = false, highlight = false, headingClass = HEADING }: { n: number; title: string; children: ReactNode; locked?: boolean; highlight?: boolean; headingClass?: string }) {
  return (
    <section className={`avoid-break mt-12 min-w-0 ${highlight ? "-mx-6 border-l-2 border-ink bg-surface-200 px-6 py-6 sm:-mx-10 sm:px-10" : ""}`} data-pm-review={highlight || undefined}>
      {highlight && <p className={`mb-2 ${LABEL}`}>PM review: 3L and SAA</p>}
      <h2 className={`border-b border-hairline pb-2 print:break-after-avoid ${headingClass}`}>{n}. {title}</h2>
      <div inert={locked} className={`mt-6 space-y-6 ${BODY} ${WRAP} ${locked ? "opacity-80" : ""}`}>{children}</div>
    </section>
  );
}

const LABELLED = /^([A-Z][A-Za-z &/()'-]{1,48}):\s+(\S[\s\S]*)$/;
/** Bullets; a leading "Label: text" renders the label semibold, plain bullets are untouched. */
export function Bullets({ items }: { items: string[] }) {
  if (items.length === 1) return <p className={`${BODY} ${WRAP}`}>{items[0]}</p>;
  return (
    <ul className={`list-disc space-y-1 pl-5 ${BODY}`}>
      {items.map((t, i) => {
        const m = LABELLED.exec(t);
        return <li key={i} className={WRAP}>{m ? <><span className="font-normal">{m[1]}:</span> {m[2]}</> : t}</li>;
      })}
    </ul>
  );
}

/** Goals: each "Label: text" starts a group rendered as a small subheading with its bullets beneath; unlabelled bullets join the previous group. */
export function GroupedBullets({ items }: { items: string[] }) {
  const groups: { label?: string; items: string[] }[] = [];
  for (const t of items) {
    const m = LABELLED.exec(t);
    if (m) {
      const g = groups.find((x) => x.label?.toLowerCase() === m[1].toLowerCase());
      if (g) g.items.push(m[2]); else groups.push({ label: m[1], items: [m[2]] });
    } else if (groups.length) groups[groups.length - 1].items.push(t);
    else groups.push({ items: [t] });
  }
  return (
    <div className="space-y-4">
      {groups.map((g, gi) => (
        <div key={gi} className="avoid-break min-w-0">
          {g.label && <SubHead>{g.label}</SubHead>}
          <ul className={`mt-1 list-disc space-y-1 pl-5 ${BODY}`}>{g.items.map((t, i) => <li key={i} className={WRAP}>{t}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

/** Multi-line free-text field in the dashed editable style; grows with its content. */
/** Fit a textarea to its content; a textarea inside a hidden (display:none) page measures 0, so keep its natural rows height then. */
export function fitTextarea(el: HTMLTextAreaElement) { el.style.height = "auto"; const h = el.scrollHeight; if (h > 0) el.style.height = `${h}px`; }
/** Auto-grow that also re-fits when the textarea first becomes visible (tabs, pages). */
export function useAutoGrow(ref: React.RefObject<HTMLTextAreaElement | null>, dep: unknown) {
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    fitTextarea(el);
    const ro = new ResizeObserver(() => { if (el.offsetParent !== null && Math.abs(el.scrollHeight - el.clientHeight) > 1) fitTextarea(el); });
    ro.observe(el); return () => ro.disconnect();
  }, [ref, dep]);
}
export function FreeText({ value, onChange, label, placeholder, rows = 3 }: { value: string; onChange: (v: string) => void; label: string; placeholder?: string; rows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(ref, value);
  return (
    <EditField>
      <textarea ref={ref} rows={rows} aria-label={label} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)}
        className={`block w-full resize-none overflow-hidden px-2 py-1 text-[15px] leading-6 placeholder:text-ink-muted ${EDIT_BOX} print:p-0`} />
    </EditField>
  );
}

/** Single-line in-place text styled as document text (contentEditable), subtle hover/focus affordance. */
export function InlineText({ value, onChange, label, placeholder = "Add a value…", inline = false }: { value: string; onChange: (v: string) => void; label: string; placeholder?: string; inline?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && el.textContent !== value) el.textContent = value;
  }, [value]);
  return (
    <EditField inline={inline}>
    <span
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-label={label}
      onInput={(e) => onChange((e.currentTarget.textContent ?? "").replace(/\s*\n\s*/g, " "))}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLElement).blur(); } }}
      onPaste={(e) => { e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain").replace(/\s*\n\s*/g, " ")); }}
      data-placeholder={placeholder}
      className={`${inline ? "inline-block min-w-[12rem]" : "block"} min-h-[28px] px-2 py-0.5 empty:before:text-ink-muted empty:before:content-[attr(data-placeholder)] ${EDIT_BOX} print:m-0 print:p-0`}
    />
    </EditField>
  );
}

/** Rows are [label, value]. When `onEdit` is given, labels not in `locked` are editable in place. Extra `children` are more cells in the same grid. */
export function KV({ rows, onEdit, locked = [], hints = {}, children }: {
  rows: readonly (readonly [string, string])[]; onEdit?: (label: string, v: string) => void; locked?: readonly string[];
  /** Optional small note under a value. */
  hints?: Record<string, string>; children?: ReactNode;
}) {
  return (
    <IpsGrid as="dl">
      {rows.map(([k, v], i) => (
        <Field key={k} label={k} hint={hints[k]} wide={!children && rows.length % 2 === 1 && i === rows.length - 1}>
          {onEdit && !locked.includes(k)
            ? <InlineText value={v} label={k} onChange={(t) => onEdit(k, t)} />
            : onEdit ? <span className="inline-flex items-center gap-2 text-ink-muted">{v}<LockedTag /></span> : v}
        </Field>
      ))}
      {children}
    </IpsGrid>
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

export function SignatureBlock({ label, image, editable = false, onChange, date }: {
  label: string; image?: string; editable?: boolean; onChange?: (dataUrl?: string) => void; date?: string;
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
      <p className={LABEL}>{label}</p>
      <div className={`mt-1 flex h-16 items-end border-b border-ink ${editable ? "bg-surface-200/50 print:bg-transparent" : ""}`}>
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
      <p className="mt-6">Date: {date || "____________"}</p>
    </div>
  );
}
