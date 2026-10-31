import { useLayoutEffect, useRef, useState } from "react";
import { toBulletItems } from "../../utils/bullets";
import { EditField, EDIT_BOX, useAutoGrow } from "./ips/parts";

const B = "• ";
const strip = (d: string) => d.split("\n").map((l) => l.replace(/^\s*[•\-*]?\s*/, "").trim()).filter(Boolean).join("\n");
const show = (v: string) => { const items = toBulletItems(v); return items.length ? items.map((t) => B + t).join("\n") : B; };
const norm = (raw: string) => (raw === "" ? "" : raw.split("\n").map((l) => (l.startsWith(B) ? l : B + l.replace(/^[•\s]+/, ""))).join("\n"));

/** Textarea showing one visible bullet per line. Stored value stays a plain newline-separated string. */
export function BulletTextarea({ value, onChange, label, placeholder }: { value: string; onChange: (v: string) => void; label: string; placeholder?: string }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const caret = useRef<number | null>(null);
  const [text, setText] = useState(() => show(value));
  // Adopt external changes only when they differ from what we last emitted.
  if (strip(text) !== strip(show(value)) && strip(text) !== value.trim()) setText(show(value));
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    if (caret.current != null) { el.setSelectionRange(caret.current, caret.current); caret.current = null; }
  }, [text]);
  useAutoGrow(ref, text);
  const apply = (raw: string) => { const n = norm(raw); setText(n); onChange(strip(n)); };
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    if (e.key !== "Backspace" || el.selectionStart !== el.selectionEnd) return;
    const pos = el.selectionStart, start = text.lastIndexOf("\n", pos - 1) + 1;
    if (text.slice(start, pos) === B && text.slice(pos).split("\n")[0] === "" && start > 0) {
      e.preventDefault(); caret.current = start - 1;
      const next = text.slice(0, start - 1) + text.slice(pos);
      setText(next); onChange(strip(next));
    }
  };
  return (
    <EditField>
      <textarea ref={ref} rows={3} aria-label={label} placeholder={placeholder} value={text}
        onFocus={() => { if (!text) setText(B); }} onBlur={() => { if (text === B) setText(""); }}
        onChange={(e) => apply(e.target.value)} onKeyDown={onKeyDown}
        className={`block min-h-[4.5rem] w-full resize-none overflow-hidden px-2 py-1 text-[15px] leading-6 placeholder:text-ink-muted ${EDIT_BOX} print:p-0`} />
    </EditField>
  );
}
