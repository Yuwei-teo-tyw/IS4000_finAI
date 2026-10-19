import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { CASE_STEPS } from "../../pages/ic/icHelpers";

/** IC stepper: every stage is a link, so the IC can jump to any page of the case (progress is kept in the store). */
export function IcStepper({ clientId, current }: { clientId: string; current: number }) {
  return (
    <ol className="mb-6 grid gap-2" style={{ gridTemplateColumns: `repeat(${CASE_STEPS.length}, minmax(0, 1fr))` }}>
      {CASE_STEPS.map((s, i) => {
        const done = i < current, active = i === current;
        return (
          <li key={s.path}>
            <Link to={`/ic/cases/${clientId}/${s.path}`} aria-current={active ? "step" : undefined} className="group flex flex-col gap-2">
              <span className={`h-1 ${active ? "bg-brand" : done ? "bg-scale-fill" : "bg-scale-track"} group-hover:bg-ink-muted`} />
              <span className="mt-2 flex items-center gap-2 text-xs text-ink-muted">{done ? <Check size={14} /> : null}Step {i + 1}</span>
              <span className={`text-sm ${active ? "font-semibold text-ink" : "text-ink-muted group-hover:text-ink"}`}>{s.label}</span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
