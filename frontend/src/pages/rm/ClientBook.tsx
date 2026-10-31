import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, CalendarClock, Landmark, Users, type LucideIcon } from "lucide-react";
import { arcApi, bookToClient } from "../../services/arcApi";
import { Button, Card, Loading, RiskScale, sgd, useAsyncResult } from "../../components/ui";
import { WelcomeBanner } from "../../components/ui/WelcomeBanner";
import { PackBackBubble } from "../../components/rm/PackBackBubble";
import { useRole } from "../../layouts/AppShell";
import { fmtDate, usePackStatus } from "./rmShared";
import type { Client } from "../../types/arc";
import type { BookClient } from "../../types/clientProfiling";
import { markNoticeSeen, useReturnedNotices } from "../../services/ipsReturnedNotice";
import { useActivated, useIpsReturned, useIpsSent } from "../../services/workflowStore";

const TODAY = new Date("2026-10-17");
const DAY = 86_400_000;
const COLS = "md:grid-cols-[1.4fr_1fr_0.8fr_1.1fr_auto] md:items-center md:gap-x-8";
const COLS_RM = "md:grid-cols-[1.3fr_1fr_0.8fr_1fr_1.1fr_1.1fr_auto] md:items-center md:gap-x-6";

function relative(date: string) {
  const d = Math.round((new Date(date).getTime() - TODAY.getTime()) / DAY);
  if (d === 0) return "today";
  if (d === 1) return "tomorrow";
  if (d === -1) return "yesterday";
  return d > 0 ? `in ${d} days` : `${-d} days ago`;
}

function StatCard({ icon: Icon, label, value, note }: { icon: LucideIcon; label: string; value: React.ReactNode; note?: string }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-ink-muted">{label}</p>
        <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-300 text-ink-muted"><Icon size={20} aria-hidden="true" /></span>
      </div>
      <p className="mt-3 text-[44px] font-light leading-[48px] text-ink">{value}</p>
      {note && <p className="mt-3 text-sm text-ink-muted">{note}</p>}
    </Card>
  );
}

function Bar({ done, total, label }: { done: number; total: number; label: string }) {
  return (
    <div>
      <div className="flex gap-1" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={label}>
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={`h-[3px] min-w-0 flex-1 rounded-none ${i < done ? "bg-brand" : "bg-hairline"}`} />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-ink-muted">{done >= total && total > 0 ? "Complete" : `${done} of ${total}`}</p>
    </div>
  );
}

/** Demo starting points: onboarding steps already done, and review-pack sections already complete (null = all). */
const SEED_ONB: Record<string, number> = { jfr: 0, sha: 2 };
const SEED_PACK: Record<string, number | null> = { ser: null, teo: null, dso: 0 };
const NONE = <p className="text-sm text-ink-muted">-</p>;

/** RM-only progress cells; "-" while a phase has not started. Onboarding: IPS draft, sent to PM, returned, active. Pack: sections complete. */
type Row = Client & { db?: { onboarding: number; pack: number } };
/** Backend book row -> the Client view this page uses, plus the DB progress. */
function fromBook(b: BookClient): Row {
  return { ...bookToClient(b), db: { onboarding: b.onboarding_progress, pack: b.monitoring_progress } };
}

/** DB progress is the baseline; workflow state only raises it when real workflow state exists for the client. */
function DbProgressCells({ clientId, db }: { clientId: string; db: { onboarding: number; pack: number } }) {
  const sent = !!useIpsSent(clientId);
  const returned = useIpsReturned(clientId);
  const active = useActivated(clientId);
  const wf = active ? 5 : returned ? 4 : sent ? 3 : 0;
  const step = Math.min(5, Math.max(db.onboarding, wf));
  const pct = Math.max(0, Math.min(100, db.pack));
  return (
    <>
      <Bar done={step} total={5} label={`Onboarding progress, ${step} of 5`} />
      <div>
        <div className="h-[3px] w-full bg-hairline" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={`Review pack progress, ${pct}%`}>
          <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-1.5 text-xs text-ink-muted">{pct}%</p>
      </div>
    </>
  );
}

function ProgressCells({ clientId, monitoring }: { clientId: string; monitoring: boolean }) {
  const sent = !!useIpsSent(clientId);
  const returned = useIpsReturned(clientId);
  const active = useActivated(clientId);
  const pack = usePackStatus(clientId);
  const done = monitoring || active;
  const step = done ? 5 : returned ? 4 : sent ? 3 : SEED_ONB[clientId] ?? 0;
  const onboarding = step > 0 ? <Bar done={step} total={5} label="Onboarding progress" /> : NONE;
  const seed = SEED_PACK[clientId];
  const packDone = !pack.ready ? 0 : seed === null ? pack.total : Math.max(pack.doneCount, seed ?? 0);
  const packCell = !done || !pack.ready || packDone === 0 ? NONE : <Bar done={packDone} total={pack.total} label="Review pack progress" />;
  return <>{onboarding}{packCell}</>;
}

export default function ClientBook() {
  const role = useRole();
  const isRm = role === "rm";
  const { data: loaded, error } = useAsyncResult<{ list: Row[]; message?: string }>(async () => {
    if (!isRm) return { list: await arcApi.listClients() };
    const b = await arcApi.listBook();
    return { list: b.clients.map(fromBook), message: b.message };
  }, [isRm]);
  const clients = loaded?.list;
  const navigate = useNavigate();
  const notices = useReturnedNotices(isRm ? (clients ?? []).filter((c) => c.status.startsWith("Onboarding")).map((c) => c.id) : []);
  const [furthestFirst, setFurthestFirst] = useState(false);
  const [filter, setFilter] = useState<"all" | "Onboarding" | "Monitoring">("all");
  if (error) return <div><WelcomeBanner role={role} /><Card><p className="text-lg text-ink">{error.message}</p></Card></div>;
  if (!clients) return <Loading />;
  if (isRm && clients.length === 0) return <div><WelcomeBanner role={role} /><Card><p className="text-lg text-ink">{loaded?.message ?? "No clients in your book"}</p></Card></div>;
  const total = clients.reduce((a, c) => a + c.aumSgd, 0);
  const sorted = [...clients].sort((a, b) => {
    const diff = (new Date(a.nextMeeting).getTime() || 0) - (new Date(b.nextMeeting).getTime() || 0);
    return furthestFirst ? -diff : diff;
  });
  const onboarding = sorted.filter((c) => c.status.startsWith("Onboarding"));
  const monitoring = sorted.filter((c) => !c.status.startsWith("Onboarding"));
  const groups = [{ title: "Onboarding", list: onboarding }, { title: "Monitoring", list: monitoring }].filter((g) => g.list.length && (filter === "all" || filter === g.title));
  const earliest = [...clients].filter((c) => c.nextMeeting).sort((a, b) => a.nextMeeting.localeCompare(b.nextMeeting))[0]?.nextMeeting;

  return (
    <div>
      <WelcomeBanner role={role} />

      <div className="mb-14 grid gap-8 md:grid-cols-3">
        <StatCard icon={Users} label="Clients" value={clients.length} note={`${onboarding.length} Onboarding, ${monitoring.length} Monitoring`} />
        <StatCard icon={Landmark} label="Assets Under Management" value={sgd(total)} />
        <StatCard icon={CalendarClock} label="Next Meeting" value={earliest ? fmtDate(earliest) : "None scheduled"} note={earliest ? relative(earliest) : undefined} />
      </div>

      <div id="client-book" className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl">Client Book</h2>
        <div className="flex items-center gap-2" role="group" aria-label="Sort clients by next meeting">
          {([[false, ArrowUpNarrowWide, "Most urgent first"], [true, ArrowDownWideNarrow, "Least urgent first"]] as const).map(([flag, Icon, label]) => (
            <button key={label} type="button" aria-label={label} title={label} aria-pressed={furthestFirst === flag} onClick={() => setFurthestFirst(flag)}
              className={`inline-flex h-10 w-10 items-center justify-center rounded-sm border border-ink transition ${furthestFirst === flag ? "bg-surface-inverse text-ink-inverse" : "bg-transparent text-ink hover:bg-surface-300"}`}>
              <Icon size={18} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>

      <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label="Filter clients by phase">
        {([["all", "All", clients.length], ["Onboarding", "Onboarding", onboarding.length], ["Monitoring", "Monitoring", monitoring.length]] as const).map(([k, label, n]) => (
          <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}
            className={`cursor-pointer rounded-full px-5 py-2 text-sm font-semibold ${filter === k ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{label} ({n})</button>
        ))}
      </div>

      <div className={`hidden px-8 pb-3 text-sm text-ink-muted md:grid ${isRm ? COLS_RM : COLS}`}>
        <span>Client</span><span>Risk appetite</span><span>AUM</span><span>Next Meeting</span>{isRm && <><span>Onboarding progress</span><span>Review pack progress</span></>}<span className="invisible">Open</span>
      </div>
      <div className="flex flex-col gap-10">
        {groups.map((g) => (
          <section key={g.title} aria-label={`${g.title} clients`}>
            <h3 className="mb-4 text-lg">{g.title} <span className="text-ink-muted">({g.list.length})</span></h3>
            <div className="flex flex-col gap-4">
        {g.list.map((c) => (
          <Card key={c.id} className={`grid gap-y-4 !px-8 !py-6 ${isRm ? COLS_RM : COLS}`}>
            <div className="flex min-w-0 flex-wrap items-center gap-3"><p className="text-xl text-ink">{c.name}</p>{isRm && notices.some((x) => x.clientId === c.id) && (
              <button type="button" title="IPS returned by the PM. Open the IPS tab" aria-label={`${c.name}, 1 returned IPS notice`} onClick={() => { notices.filter((x) => x.clientId === c.id).forEach((x) => markNoticeSeen(x.key, "book")); navigate(`/rm/clients/${c.id}/documents`); }}
                className="cursor-pointer rounded-full border border-brand px-2 text-sm font-semibold text-brand hover:bg-surface-300">{notices.filter((x) => x.clientId === c.id).length}</button>
            )}{isRm && <PackBackBubble clientId={c.id} />}</div>
            {c.riskCap ? <div><RiskScale value={c.riskCap} /><p className="mt-2 text-xs text-ink-muted">{c.riskCategory}, {c.riskCap} of 5</p></div> : NONE}
            <p className="text-sm font-semibold">{sgd(c.aumSgd)}</p>
            {c.nextMeeting ? (
              <div className="text-sm">
                <p className="font-semibold">{fmtDate(c.nextMeeting)}</p>
                <p className="mt-1 text-ink-muted">{relative(c.nextMeeting)}</p>
              </div>
            ) : NONE}
            {isRm && (c.db ? <DbProgressCells clientId={c.id} db={c.db} /> : <ProgressCells clientId={c.id} monitoring={g.title === "Monitoring"} />)}
            <div><Button to={`/${role}/clients/${c.id}`}>Open</Button></div>
          </Card>
        ))}
      </div>
          </section>
        ))}
      </div>
    </div>
  );
}
