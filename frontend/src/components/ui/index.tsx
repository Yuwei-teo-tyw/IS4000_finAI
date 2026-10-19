import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Check, Minus } from "lucide-react";

/** Icon-only direction cue (no text). Colours: text-up / text-down / text-ink-muted. Number = sign of delta. */
export function DirectionArrow({ d, size = 14 }: { d: "up" | "down" | "flat" | number; size?: number }) {
  const dir = typeof d === "number" ? (d > 0 ? "up" : d < 0 ? "down" : "flat") : d;
  const Icon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : Minus;
  const cls = dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-ink-muted";
  const label = dir === "up" ? "Up" : dir === "down" ? "Down" : "No change";
  return <Icon size={size} role="img" aria-label={label} className={`inline-block shrink-0 align-[-2px] ${cls}`} />;
}

/** Load async data once; pages stay free of fetch plumbing. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  useEffect(() => {
    let live = true;
    fn().then((d) => live && setData(d));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}

/** Lux: one display heading + a short brand rule. Light weight, never bold. */
export function PageHeader({ eyebrow, title, subtitle, actions }: { eyebrow?: string; title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-12 flex flex-wrap items-end justify-between gap-6">
      <div className="max-w-[680px]">
        {eyebrow && <p className="mb-3 text-xs text-ink-muted">{eyebrow}</p>}
        <h1 className="text-[40px] leading-[46px]">{title}</h1>
        <div className="mt-5 h-[3px] w-12 bg-brand" />
        {subtitle && <p className="mt-5 text-[20px] font-light leading-[30px] text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-4">{actions}</div>}
    </header>
  );
}

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mb-16">
      <div className="mb-7 max-w-[680px]">
        <h2 className="text-[28px] leading-[34px]">{title}</h2>
        {hint && <p className="mt-2 text-sm text-ink-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function Card({ children, className = "", accent: _accent = false }: { children: ReactNode; className?: string; accent?: boolean }) {
  return <div className={`rounded-lg border border-hairline bg-surface-100 p-6 shadow-card ${className}`}>{children}</div>;
}

type Tone = "navy" | "gold" | "green" | "red" | "amber" | "grey" | "sky";
/** Lux has no status colours beyond positive/negative text: tones differ by weight/border, always with a word. */
const tones: Record<Tone, string> = {
  navy: "bg-surface-inverse text-ink-inverse",
  gold: "bg-surface-300 text-ink",
  green: "bg-surface-300 text-positive border border-positive",
  red: "bg-surface-300 text-negative border border-negative",
  amber: "bg-surface-200 text-ink border border-hairline-strong",
  grey: "bg-surface-300 text-ink-muted",
  sky: "bg-surface-300 text-ink",
};
export function Badge({ children, tone = "grey" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`inline-flex items-center rounded-sm px-3 py-1 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
}

/** Risk scale: `value` of `max` dashes filled in brand red, with caption. */
export function RiskScale({ value, max = 5 }: { value: number; max?: number }) {
  return (
    <div role="img" aria-label={`Product risk limit ${value} of ${max}`}>
      <div className="flex gap-1" aria-hidden="true">
        {Array.from({ length: max }, (_, i) => (
          <span key={i} className={`h-[3px] w-6 rounded-none ${i < value ? "bg-brand" : "bg-scale-track"}`} />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-ink-muted" aria-hidden="true">Limit {value} of {max}</p>
    </div>
  );
}

/** "primary" (default) and "gold" = brand red fill; "secondary" and "ghost" = outlined neutral (back / cancel / sort / toggle). */
export function Button({ children, variant = "primary", to, onClick, disabled, type = "button", size = "md" }: {
  children: ReactNode; variant?: "primary" | "gold" | "secondary" | "ghost"; size?: "sm" | "md"; to?: string; onClick?: () => void; disabled?: boolean; type?: "button" | "submit";
}) {
  const base = "inline-flex items-center gap-2 rounded-sm text-[15px] font-semibold transition disabled:bg-surface-300 disabled:text-ink-muted disabled:pointer-events-none";
  const v = {
    gold: "bg-brand text-on-brand hover:bg-brand-hover",
    primary: "bg-brand text-on-brand hover:bg-brand-hover",
    secondary: "border border-ink text-ink bg-transparent hover:bg-surface-300",
    ghost: "border border-ink text-ink bg-transparent hover:bg-surface-300",
  }[variant];
  const cls = `${base} ${size === "sm" ? "min-h-9 px-4" : "min-h-12 px-6"} ${v}`;
  return to ? <Link to={to} className={cls}>{children}</Link> : <button type={type} onClick={onClick} disabled={disabled} className={cls}>{children}</button>;
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <Card>
      <p className="text-sm text-ink-muted">{label}</p>
      <p className="mt-3 text-[44px] font-light leading-[48px] text-ink">{value}</p>
      {note && <p className="mt-3 text-sm text-ink-muted">{note}</p>}
    </Card>
  );
}

/** The user-journey spine. Put one on every workflow page. Current step = brand bar. */
export function Stepper({ steps, current }: { steps: { label: string; hint?: string }[]; current: number }) {
  return (
    <ol className="mb-14 grid gap-2" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      {steps.map((s, i) => {
        const done = i < current, active = i === current;
        return (
          <li key={s.label} className="flex flex-col gap-2">
            <span className={`h-1 ${active ? "bg-brand" : done ? "bg-scale-fill" : "bg-scale-track"}`} />
            <span className="mt-2 flex items-center gap-2 text-xs text-ink-muted">
              {done ? <Check size={14} /> : null}Step {i + 1}
            </span>
            <span className={`text-sm ${active ? "font-semibold text-ink" : "text-ink-muted"}`}>{s.label}</span>
            {s.hint && <span className="text-xs text-ink-muted">{s.hint}</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** "What to do next" band: one primary action per page. */
export function NextAction({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="mb-14 flex flex-wrap items-center justify-between gap-6 bg-surface-200 p-6">
      <div className="max-w-[680px]">
        <p className="text-xs text-ink-muted">Next step</p>
        <h3 className="mt-1 text-[22px] font-normal leading-7">{title}</h3>
        {body && <p className="mt-2 text-sm text-ink-muted">{body}</p>}
      </div>
      {action}
    </div>
  );
}

const gateTone = { not_started: "grey", pending: "amber", approved: "green", reset: "red" } as const;
const gateText = { not_started: "Not started", pending: "Awaiting approval", approved: "Approved", reset: "Reset" } as const;
export function GateChip({ id, state }: { id: string; state: keyof typeof gateTone }) {
  return <Badge tone={gateTone[state]}>{id} · {gateText[state]}</Badge>;
}

/** Lux: rows separated by hairlines, no boxes; header is plain muted text on a light band. */
export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-hairline bg-surface-100">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-200 text-ink-muted">
          <tr>{head.map((h) => <th key={h} className="px-6 py-4 text-xs font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-hairline">{r.map((c, j) => <td key={j} className="px-6 py-5 align-top">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const sgd = (n: number) => `S$${(n / 1_000_000).toFixed(n >= 1_000_000 ? 1 : 2)}m`;
export const sgdFull = (n: number) => `S$${n.toLocaleString("en-SG")}`;

export function Loading() {
  return <p className="py-16 text-center text-sm text-ink-muted">Loading…</p>;
}
export { toBulletItems, toBulletText, BulletList, BulletTextarea } from "./BulletText";
export type { BulletTextareaProps } from "./BulletText";
export { CitationTag } from "./CitationTag";
export { useSliceTooltip, SliceTooltip } from "./SliceTooltip";
export type { SliceTip } from "./SliceTooltip";
export { SignatureBlock, SCRIPT_FONT } from "./SignatureBlock";
export type { SignatureRole } from "./SignatureBlock";
