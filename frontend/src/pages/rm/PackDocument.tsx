import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { GenevaMark } from "../../components/documents/GenevaMark";
import { SCRIPT_FONT } from "../../components/ui";
import { ROLE_LABEL, type AllocationRow, type Holding, type PackSection, type Role } from "../../types/arc";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { loadPackDrafts, loadSignatures, savePackDraft, subscribePackDrafts, subscribeSignatures, usePackHistory, type PackSignature } from "../../services/packDraftStore";
import { useRole } from "../../layouts/AppShell";
import { hasHeadings } from "../../services/packBlocks";
import { SectionBlocksView, useSeededBlocks, sourcesFor, Tagged, HangList, isSources, isSignoff, fmtDate, usePackStatus, isHiddenFor, PendingBox } from "./rmShared";

const ROLES: Role[] = ["rm", "pm", "ps"];
const A3_PRINT_CSS = "@page a3 { size: A3; margin: 18mm; } @media print { .a3-sheet { page: a3; max-width: none; } }";
const cap = "text-[12px] uppercase tracking-[0.14em] text-ink-muted";
const quarterOf = (d: Date) => `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
const fmtWhen = (iso: string) => new Date(iso).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });


function DocBlocks({ clientId, n, body, chart }: { clientId: string; n: number; body: string; chart?: PackSection["chart"] }) {
  const blocks = useSeededBlocks(clientId, n, body, chart);
  return <SectionBlocksView blocks={blocks} clientId={clientId} sub="text-[13px] font-normal" />;
}

function SigMark({ g, who }: { g: PackSignature; who: string }) {
  return g.typed || !g.dataUrl
    ? <span className="text-[22px] leading-tight text-ink" style={{ fontFamily: SCRIPT_FONT }}>{g.name}</span>
    : <img src={g.dataUrl} alt={`${who} signature`} className="h-12 max-w-[140px] object-contain" />;
}

/** Owner's signature line under a section: signed mark, name and date, or a quiet 'Not yet signed' hairline. */
function SectionSign({ g, who }: { g?: PackSignature; who: string }) {
  return (
    <div className="avoid-break mt-10 max-w-sm">
      {g ? (
        <div className="flex h-12 items-end"><SigMark g={g} who={who} /></div>
      ) : <div className="h-12" />}
      <div className="h-px w-full bg-hairline-strong" />
      <p className="mt-1 text-xs text-ink-muted">{g ? `${who} · ${fmtWhen(g.signedAt)}` : "Not yet signed"}</p>
    </div>
  );
}

/** Coupling note: reads PM progress (usePmProgress) and ROLE_PEOPLE directly; revisit when a backend pack API exists. */
/** Single-column printed rendering of the review pack. Reads drafts, signatures and PM progress live; mock text is used only where no draft exists. */
export function PackDocument({ clientId, clientName, version, pack, approved }: {
  clientId: string; clientName: string; version: string; pack: PackSection[]; alloc: AllocationRow[] | undefined; holdings: Holding[] | undefined; approved: boolean;
}) {
  const [drafts, setDrafts] = useState(() => loadPackDrafts(clientId));
  useEffect(() => { setDrafts(loadPackDrafts(clientId)); return subscribePackDrafts(clientId, setDrafts); }, [clientId]);
  const [sigs, setSigs] = useState(() => loadSignatures(clientId));
  useEffect(() => { setSigs(loadSignatures(clientId)); return subscribeSignatures(clientId, setSigs); }, [clientId]);
  const now = new Date();

  const gateOf = (g: string) => {
    const secs = pack.filter((x) => x.gate === g);
    if (g === "G4") return approved ? "Approved" : "Pending";
    return secs.length && secs.every((x) => x.status === "approved") ? "Approved" : secs.length && secs.every((x) => x.status !== "draft") ? "Ready" : "Pending";
  };
  const gates = Array.from(new Set(pack.map((x) => x.gate).filter(Boolean) as string[])).sort();
  const { doneCount, complete } = usePackStatus(clientId);
  const role = useRole();
  const [editing, setEditing] = useState<number | null>(null);
  const [buf, setBuf] = useState("");
  const startEdit = (n: number, text: string) => { setBuf(text); setEditing(n); };
  const saveEdit = (n: number) => { savePackDraft(clientId, n, buf.trim(), role); setEditing(null); };

  const allHistory = usePackHistory(clientId);
  const history = allHistory.slice(0, 8);
  const lastBy = (n: number): Role | undefined => allHistory.find((h) => h.section === n)?.role;
  const Rule = () => <div className="h-px w-full bg-hairline" />;
  const th = "py-2 pr-4 text-left text-xs font-normal text-ink-muted";

  return (
    <article className="a3-sheet mx-auto aspect-[297/420] w-full min-w-0 max-w-[1123px] border border-hairline bg-surface-100 px-8 py-14 text-ink shadow-card sm:px-16 sm:py-20 lg:px-24 lg:py-24 print:aspect-auto print:border-0 print:p-0 print:shadow-none">
      <style>{A3_PRINT_CSS}</style>
      <header className="mb-16">
        <GenevaMark className="mb-14" />
        <p className={cap}>Quarterly review pack</p>
        <h1 className="mt-3 text-[40px] font-light leading-[48px]">{clientName}</h1>
        <div className="mt-6 h-px w-full bg-ink" />
        <dl className="mt-2 text-[15px]">
          {[
            ["Client", clientName],
            ["Review quarter", quarterOf(now)],
            ["Date", fmtDate(now.toISOString())],
            ["Version", version],
            ["Gates", gates.map((g) => `${g} ${gateOf(g).toLowerCase()}`).join("  ·  ")],
          ].map(([k, v]) => (
            <div key={k} className="flex flex-wrap items-baseline gap-x-6 border-b border-hairline py-3">
              <dt className={`${cap} w-36 shrink-0`}>{k}</dt><dd className="min-w-0 flex-1 [overflow-wrap:anywhere]">{v}</dd>
            </div>
          ))}
        </dl>
        {doneCount < pack.length && <p className="mt-6 text-sm italic text-ink-muted">Draft: {pack.length - doneCount} section{pack.length - doneCount > 1 ? "s" : ""} still to be completed. Not for client distribution.</p>}
      </header>

      <div className="space-y-16">
        {pack.map((x, idx) => {
          const hidden = isHiddenFor(x, role, complete);
          const mine = x.owner === role;
          const text = drafts[x.n] ?? x.body;
          const owed = editing !== x.n && !isSignoff(x) && !isSources(x) && (!text.trim() || (drafts[x.n] === undefined && x.status === "draft"));
          return (
            <section key={x.n}>
              <Rule />
              <h2 className="mt-8 flex items-baseline gap-5 text-[28px] font-light leading-9 [overflow-wrap:anywhere]">
                <span className="w-9 shrink-0 text-[18px] text-ink-muted">{idx + 1}</span>{x.title}
              </h2>
              <p className="mb-8 mt-2 pl-14 text-xs text-ink-muted">{ROLE_LABEL[x.owner]} ({ROLE_PEOPLE[x.owner].person}){!mine && !isSignoff(x) && !hidden && <span className="no-print ml-3 inline-flex items-center gap-1 uppercase tracking-[0.12em]"><Lock size={11} />Read only</span>}</p>
              <div className="pl-0 text-[16px] font-light leading-8 text-ink-700 sm:pl-14">
                {hidden ? (
                  <PendingBox owner={x.owner} />
                ) : owed ? (
                  editing === x.n ? null : mine
                    ? <button type="button" onClick={() => startEdit(x.n, drafts[x.n] ?? x.body)} title="Click to edit" className="cursor-text rounded-none border-0 bg-transparent p-0 text-left italic text-ink-muted hover:text-ink focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2">To be completed by {ROLE_LABEL[x.owner]} ({ROLE_PEOPLE[x.owner].person}).</button>
                    : <p className="italic text-ink-muted">To be completed by {ROLE_LABEL[x.owner]} ({ROLE_PEOPLE[x.owner].person}).</p>
                ) : isSignoff(x) ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b border-hairline-strong"><th className={th}>Role</th><th className={th}>Name</th><th className={th}>Signature</th><th className={th}>Signed on</th></tr></thead>
                      <tbody>{ROLES.map((r) => {
                        const g = sigs[r];
                        return (
                          <tr key={r} className="avoid-break border-b border-hairline align-middle">
                            <td className="py-4 pr-4">{ROLE_LABEL[r]}</td>
                            <td className="pr-4">{ROLE_PEOPLE[r].person}</td>
                            <td className="pr-4">{g ? <SigMark g={g} who={ROLE_PEOPLE[r].person} /> : <span className="italic text-ink-muted">Pending</span>}</td>
                            <td className="text-ink-muted">{g ? fmtWhen(g.signedAt) : "____________"}</td>
                          </tr>
                        );
                      })}</tbody>
                    </table>
                  </div>
                ) : isSources(x) ? (
                  <div className="space-y-8">
                                        {ROLES.map((r) => (
                      <div key={r} className="avoid-break">
                        <h3 className="mb-3 text-[13px] font-normal uppercase tracking-[0.12em] text-ink">{ROLE_LABEL[r]}</h3>
                        <HangList items={sourcesFor(drafts[x.n], r)} className="text-[15px]" />
                      </div>
                    ))}
                  </div>
                ) : editing === x.n ? (
                  <div className="no-print">
                    <textarea value={buf} onChange={(e) => setBuf(e.target.value)} rows={Math.min(22, Math.max(8, buf.split("\n").length + 1))} autoFocus aria-label={`Edit ${x.title}`}
                      className="block w-full resize-y rounded-sm border border-hairline-strong bg-surface-100 px-4 py-3 text-[15px] font-light leading-7 text-ink" />
                    <p className="mt-1 text-xs text-ink-muted">{hasHeadings(buf) ? "Headings start with ##; separate blocks with a blank line." : "One point per line."}</p>
                    <div className="mt-3 flex gap-2">
                      <button type="button" onClick={() => saveEdit(x.n)} className="min-h-8 border border-hairline-strong px-3 text-[13px] text-ink hover:bg-surface-300">Save</button>
                      <button type="button" onClick={() => setEditing(null)} className="min-h-8 border border-hairline px-3 text-[13px] text-ink-muted hover:bg-surface-300">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div role={mine ? "button" : undefined} tabIndex={mine ? 0 : undefined} title={mine ? "Click to edit" : undefined} onClick={mine ? () => startEdit(x.n, text) : undefined} onKeyDown={mine ? (e) => { if (e.key === "Enter") startEdit(x.n, text); } : undefined}
                    className={`-mx-3 px-3 py-1 transition-colors print:m-0 print:p-0 ${mine ? "cursor-text hover:bg-surface-200" : ""}`}>
                    <DocBlocks clientId={clientId} n={x.n} body={x.body} chart={x.chart} />
                    {lastBy(x.n) && <p className="no-print mt-3 text-xs text-ink-muted">Last edited by {ROLE_LABEL[lastBy(x.n)!]}</p>}
                  </div>
                )}
                {!hidden && !isSignoff(x) && <SectionSign g={sigs[x.owner]} who={ROLE_PEOPLE[x.owner].person} />}
              </div>
            </section>
          );
        })}
      </div>

      {history.length > 0 && (
        <section className="mt-16 avoid-break">
          <Rule />
          <h2 className={`${cap} mt-6`}>Edit history</h2>
          <ul className="mt-3 text-[13px] text-ink-muted">
            {history.map((h, i) => (
              <li key={i} className="border-b border-hairline py-2">{fmtDate(h.at)} · {ROLE_LABEL[h.role]} · {h.section === 0 ? "handed over" : `Section ${pack.findIndex((p) => p.n === h.section) + 1 || h.section}`}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="mt-20 border-t border-hairline pt-4 text-xs text-ink-muted">
        Geneva  ·  Quarterly Review Pack  ·  {clientName}  ·  {version}  ·  <Tagged text={approved ? "Final" : "Draft, not for client distribution"} />
      </footer>
    </article>
  );
}
