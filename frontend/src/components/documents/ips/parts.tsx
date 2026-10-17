import type { ReactNode } from "react";

export const WRAP = "break-words [overflow-wrap:anywhere] min-w-0";

/** Split a body into bullet items on newlines and sentence ends. */
export const toBullets = (text: string): string[] =>
  text.split(/\n+|(?<=[.;])\s+(?=[A-Z0-9])/).map((s) => s.trim().replace(/\.$/, "")).filter(Boolean);

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

export function KV({ rows }: { rows: readonly (readonly [string, string])[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2">
      {rows.map(([k, v]) => (
        <div key={k} className="avoid-break min-w-0 border-b border-hairline pb-2">
          <dt className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{k}</dt>
          <dd className={`mt-0.5 ${WRAP}`}>{v}</dd>
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

export function SignatureBlock({ label }: { label: string }) {
  return (
    <div className="avoid-break min-w-0">
      <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{label}</p>
      <div className="h-12 border-b border-ink" />
      <p className="mt-1 text-[12px] text-ink-muted">Signature</p>
      <p className="mt-6">Date: ____________</p>
    </div>
  );
}
