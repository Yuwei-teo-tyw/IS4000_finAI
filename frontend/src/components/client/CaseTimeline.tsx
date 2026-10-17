import { Check } from "lucide-react";

export interface CaseStep { who: string; what: string; by: string; state: "done" | "waiting" | "not_started" }
const WORD = { done: "Done", waiting: "Waiting", not_started: "Not started" } as const;

/** Vertical case-status timeline: filled+check = done, ringed ink = waiting, hairline ring = not started. */
export function CaseTimeline({ steps }: { steps: CaseStep[] }) {
  return (
    <ol className="relative ml-3 border-l border-hairline-strong pl-10">
      {steps.map((s, i) => (
        <li key={i} className="relative mb-9 last:mb-0">
          <span className={`absolute -left-[51px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full ${
            s.state === "done" ? "bg-positive text-on-brand"
            : s.state === "waiting" ? "border-2 border-ink bg-surface-100"
            : "border border-hairline-strong bg-surface-100"}`}>
            {s.state === "done" && <Check size={12} />}
          </span>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <p className={`text-base ${s.state === "not_started" ? "text-ink-muted" : "text-ink"}`}>{s.who}</p>
            <span className={`text-xs ${s.state === "done" ? "text-positive" : s.state === "waiting" ? "text-ink" : "text-ink-muted"}`}>{WORD[s.state]}</span>
          </div>
          <p className="mt-1 text-sm text-ink-muted">{s.what} · {s.by}</p>
        </li>
      ))}
    </ol>
  );
}
