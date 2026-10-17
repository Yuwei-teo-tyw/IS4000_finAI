import type { ReactNode } from "react";
import type { Role } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { ROLE_LABEL } from "../../types/arc";
import { GenevaMark } from "../documents/GenevaMark";

export interface DocSection { n: number; title: string; owner: Role; complete: boolean; body: ReactNode }

export const pendingLabel = (owner: Role) => `${ROLE_LABEL[owner]} (${ROLE_PEOPLE[owner].person})`;

/** Roles that still owe at least one section. */
export function pendingRoles(sections: DocSection[]): Role[] {
  return Array.from(new Set(sections.filter((s) => !s.complete).map((s) => s.owner)));
}

interface Props {
  docTitle: string; clientName: string; version: string; date: string; sections: DocSection[];
}

/** Print-first formal rendering of a document composed from sections owned by different roles. */
export function CompiledDocument({ docTitle, clientName, version, date, sections }: Props) {
  const pending = sections.filter((s) => !s.complete);
  const draft = pending.length > 0;
  return (
    <article className="mx-auto w-full min-w-0 max-w-full md:max-w-3xl border border-hairline bg-surface-100 px-6 py-10 text-ink shadow-card sm:px-12 sm:py-14 print:shadow-none">
      <header className="mb-12 border-b border-ink pb-8">
        <GenevaMark className="mb-8" />
        {draft && (
          <div className="mb-8 border-2 border-dashed border-negative px-5 py-4 text-center text-sm font-semibold uppercase tracking-widest text-negative">
            Draft — Incomplete
            <div className="mt-1 text-xs font-normal normal-case tracking-normal">
              {pending.length} section{pending.length > 1 ? "s" : ""} still to be completed by {pendingRoles(sections).map((r) => ROLE_LABEL[r]).join(" and ")}.
            </div>
          </div>
        )}
        <h1 className="break-words [overflow-wrap:anywhere] text-4xl">{docTitle}</h1>
        <dl className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-3 text-sm">
          <div><dt className="text-ink-muted">Client</dt><dd className="break-words font-semibold [overflow-wrap:anywhere]">{clientName}</dd></div>
          <div><dt className="text-ink-muted">Version</dt><dd className="font-semibold">{version}</dd></div>
          <div><dt className="text-ink-muted">Date</dt><dd className="font-semibold">{date}</dd></div>
        </dl>
      </header>

      <div className="flex flex-col gap-10">
        {sections.map((s) => (
          <section key={s.n} className="min-w-0">
            <div className="avoid-break mb-3 flex flex-wrap items-baseline justify-between gap-3 border-b border-hairline pb-2">
              <h2 className="min-w-0 break-words [overflow-wrap:anywhere] text-xl"><span className="mr-2 text-sm font-normal text-ink-muted">{s.n}.</span>{s.title}</h2>
              <span className={`border px-3 py-1 text-xs font-semibold uppercase tracking-wider ${s.complete ? "border-ink text-ink" : "border-dashed border-negative text-negative"}`}>
                {s.complete ? "Complete" : `Pending — ${pendingLabel(s.owner)}`}
              </span>
            </div>
            <p className="mb-3 text-xs text-ink-muted">Section owner: {ROLE_LABEL[s.owner]} ({ROLE_PEOPLE[s.owner].person})</p>
            {s.complete ? (
              <div className="min-w-0 max-w-full overflow-hidden whitespace-pre-wrap break-words text-base leading-loose [overflow-wrap:anywhere]">{s.body}</div>
            ) : (
              <div className="border-2 border-dashed border-hairline-strong bg-surface-200 px-6 py-10 text-center text-sm text-ink-muted">
                To be completed by {ROLE_LABEL[s.owner]} ({ROLE_PEOPLE[s.owner].person})
              </div>
            )}
          </section>
        ))}
      </div>

      <footer className="mt-14 border-t border-hairline pt-4 text-xs text-ink-muted">
        Geneva · {docTitle} · {clientName} · {version} · {draft ? "Draft, not for client distribution" : "Final"}
      </footer>
    </article>
  );
}
