import type { KeyboardEvent } from "react";
import { CitationTag } from "./CitationTag";
import { toBulletItems, toBulletText } from "../../utils/bullets";

const B = "• ";

export { toBulletItems, toBulletText };

const TAG = /(\[[A-Z]{2,5}-[^\]\s]+\])/g;
const TAG_ONE = /^\[[A-Z]{2,5}-[^\]\s]+\]$/;

export function BulletList({ text, empty = "No reason given", className = "" }: { text?: string; empty?: string; className?: string }) {
  const items = toBulletItems(text ?? "");
  if (items.length === 0) return <p className={`text-sm text-ink-muted ${className}`}>{empty}</p>;
  return (
    <ul className={`list-disc space-y-1.5 pl-5 text-sm leading-relaxed marker:text-ink-muted ${className}`}>
      {items.map((it, i) => (
        <li key={i}>{it.split(TAG).map((p, j) => (TAG_ONE.test(p) ? <CitationTag key={j} tag={p.slice(1, -1)} /> : <span key={j}>{p}</span>))}</li>
      ))}
    </ul>
  );
}

export interface BulletTextareaProps {
  value: string; onChange: (value: string) => void; rows?: number; className?: string;
  placeholder?: string; disabled?: boolean; id?: string; "aria-label"?: string;
}

export function BulletTextarea({ value, onChange, rows = 5, className = "", placeholder, disabled, id, "aria-label": ariaLabel }: BulletTextareaProps) {
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    const el = e.currentTarget;
    const s = el.selectionStart, en = el.selectionEnd;
    const lineStart = value.lastIndexOf("\n", s - 1) + 1;
    const line = value.slice(lineStart, s);
    if (value.trim() === "") { onChange(B); requestAnimationFrame(() => el.setSelectionRange(B.length, B.length)); return; }
    if (/^\s*[•\-*]?\s*$/.test(line) && s === en) return; // empty bullet line: no blank bullets
    const ins = "\n" + B;
    onChange(value.slice(0, s) + ins + value.slice(en));
    const pos = s + ins.length;
    requestAnimationFrame(() => el.setSelectionRange(pos, pos));
  };
  const onFocus = () => {
    if (!value.trim()) onChange(B);
    else { const n = toBulletText(value); if (n !== value) onChange(n); }
  };
  return (
    <textarea id={id} rows={rows} value={value} disabled={disabled} aria-label={ariaLabel} placeholder={placeholder}
        onFocus={onFocus} onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown}
        className={`block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-4 py-3 text-[17px] font-light leading-8 text-ink disabled:opacity-60 ${className}`} />
  );
}
