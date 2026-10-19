import { Badge, Card } from "../ui";
import { ROLE_LABEL } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import type { DocSection } from "./CompiledDocument";

export function ContributionsPanel({ sections, className = "mb-10" }: { sections: DocSection[]; className?: string }) {
  const done = sections.filter((s) => s.complete).length;
  return (
    <Card className={`w-full min-w-0 !p-6 ${className}`}>
      <div className="mb-5">
        <h2 className="text-xl">Who Still Needs To Contribute</h2>
        <p className="mt-1 text-sm text-ink-muted">{done} of {sections.length} sections complete</p>
      </div>
      <ul className="flex flex-col divide-y divide-hairline">
        {sections.map((s, idx) => (
          <li key={s.n} className="flex items-start justify-between gap-3 py-4 text-sm">
            <div className="min-w-0">
              <p className="break-words [overflow-wrap:anywhere]"><span className="mr-2 text-ink-muted">{idx + 1}.</span>{s.title}</p>
              <p className="mt-1 break-words text-xs text-ink-muted">{ROLE_LABEL[s.owner]} ({ROLE_PEOPLE[s.owner].person})</p>
            </div>
            <span className="shrink-0"><Badge tone={s.complete ? "green" : "amber"}>{s.complete ? "Complete" : "Pending"}</Badge></span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

