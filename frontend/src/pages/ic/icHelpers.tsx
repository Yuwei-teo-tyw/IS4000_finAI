import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../../components/ui";

export const ASSETS = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"] as const;

/** Max share (%) of growth assets (equities + hedge funds + private markets) allowed per risk cap 1-5. */
export const growthLimit = (riskCap: number) => ({ 1: 15, 2: 30, 3: 50, 4: 70, 5: 90 } as Record<number, number>)[riskCap] ?? 50;
export const growthShare = (v: number[]) => v[2] + v[3] + v[4];
export const sum = (v: number[]) => v.reduce((a, b) => a + b, 0);

export function NumInput({ value, onChange, suffix, width = "w-28" }: { value: number; onChange: (n: number) => void; suffix?: string; width?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <input
        type="number" value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`${width} rounded-md border border-ink-200 bg-surface-100 px-3 py-2 text-right text-sm text-ink focus:border-ink focus:outline-none`}
      />
      {suffix && <span className="text-sm text-ink-500">{suffix}</span>}
    </span>
  );
}

export function Bar({ pct, tone = "navy" }: { pct: number; tone?: "navy" | "gold" | "red" }) {
  const c = { navy: "bg-scale-fill", gold: "bg-scale-fill", red: "bg-negative" }[tone];
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-sm bg-scale-track">
      <div className={`h-full ${c}`} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}

export function Msg({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <p className={`rounded-md px-4 py-3 text-sm ${ok ? "bg-surface-300 text-positive" : "bg-surface-300 text-negative"}`}>{children}</p>
  );
}

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="text-sm font-semibold text-ink underline underline-offset-4">{children}</Link>;
}

export const Tone = Badge;

/** Split text into plain text and [TAG] citation pieces. */
export function splitCitations(text: string): { text: string; tags: string[] } {
  const tags = Array.from(text.matchAll(/\[([A-Za-z0-9-]+)\]/g)).map((m) => m[1]);
  return { text: text.replace(/\s*\[[A-Za-z0-9-]+\]/g, ""), tags };
}
