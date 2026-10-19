import type { ReactNode } from "react";
import type { Role } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { ROLE_LABEL } from "../../types/arc";
import { GenevaMark } from "../documents/GenevaMark";

export interface DocSection { n: number; title: string; owner: Role; complete: boolean; body: ReactNode; wide?: boolean }

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
    <article className="a3-sheet mx-auto aspect-[297/420] w-full min-w-0 max-w-[1123px] border border-hairline bg-surface-100 px-6 py-10 text-ink shadow-card sm:px-14 sm:py-14 lg:px-24 lg:py-20 print:aspect-auto print:border-0 print:shadow-none">
      <style>{"@page a3 { size: A3; margin: 18mm; } @media print { .a3-sheet { page: a3; max-width: none; } }"}</style>
      <header className="mb-12">
        <GenevaMark className="mb-10" />
        {draft && (
          <div className="mb-8 border border-dashed border-negative px-6 py-4 text-center text-[13px] font-medium uppercase tracking-[0.2em] text-negative">
            Draft, incomplete
            <div className="mt-1 text-xs font-light normal-case tracking-normal">
              {pending.length} section{pending.length > 1 ? "s" : ""} still to be completed by {pendingRoles(sections).map((r) => ROLE_LABEL[r]).join(" and ")}.
            </div>
          </div>
        )}
        <h1 className="break-words text-[34px] font-light leading-[40px] [overflow-wrap:anywhere]">{docTitle}</h1>
        <div className="mt-4 h-px w-full bg-brand" />
        <dl className="mt-6 grid grid-cols-1 gap-6 text-sm sm:grid-cols-3">
          <div><dt className="text-[12px] uppercase tracking-[0.12em] text-ink-muted">Client</dt><dd className="mt-1 break-words text-base [overflow-wrap:anywhere]">{clientName}</dd></div>
          <div><dt className="text-[12px] uppercase tracking-[0.12em] text-ink-muted">Version</dt><dd className="mt-1 text-base">{version}</dd></div>
          <div><dt className="text-[12px] uppercase tracking-[0.12em] text-ink-muted">Date</dt><dd className="mt-1 text-base">{date}</dd></div>
        </dl>
      </header>

      <div className="grid grid-cols-1 gap-x-12 gap-y-12 md:grid-cols-2">
        {sections.map((s, idx) => (
          <section key={s.n} className={`min-w-0 ${s.wide ? "md:col-span-2" : ""}`}>
            <div className="avoid-break flex flex-wrap items-baseline justify-between gap-3 border-t border-ink pt-4">
              <h2 className="min-w-0 break-words text-[22px] font-light [overflow-wrap:anywhere]"><span className="mr-3 text-sm text-ink-muted">{String(idx + 1).padStart(2, "0")}</span>{s.title}</h2>
              <span className={`border px-3 py-1 text-[11px] uppercase tracking-[0.14em] ${s.complete ? "border-ink text-ink" : "border-dashed border-negative text-negative"}`}>
                {s.complete ? "Complete" : "Pending"}
              </span>
            </div>
            <p className="mb-5 mt-2 text-xs text-ink-muted">{ROLE_LABEL[s.owner]} ({ROLE_PEOPLE[s.owner].person})</p>
            {s.complete ? (
              <div className="min-w-0 max-w-full text-[15px] leading-7 [overflow-wrap:anywhere]">{s.body}</div>
            ) : (
              <div className="border border-dashed border-hairline-strong bg-surface-200 px-6 py-10 text-center text-sm text-ink-muted">
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
