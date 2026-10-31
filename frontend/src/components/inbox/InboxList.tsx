import { useState } from "react";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, AlertTriangle, Inbox, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, Card, Loading, PageHeader } from "../ui";
import { WelcomeBanner } from "../ui/WelcomeBanner";
import type { Role } from "../../types/arc";

export interface InboxRow { id: string; clientId: string; clientName: string; priority: "normal" | "high"; nextMeeting: string; finished?: boolean; /** Request type, e.g. "Onboarding: fill 3L and SAA" or "Quarterly review". */ kind?: string }
type InboxItem = InboxRow;
const fmtDate = (s: string) => new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });


const COLS = "md:grid-cols-[1.6fr_1.2fr_1.2fr_auto] md:items-center md:gap-x-8";
const COLS_KIND = "md:grid-cols-[1.6fr_1.4fr_1.2fr_1.2fr_auto] md:items-center md:gap-x-8";

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

/** Urgency order: high priority first, then soonest next meeting. */
function byUrgency(a: InboxItem, b: InboxItem) {
  const p = Number(b.priority === "high") - Number(a.priority === "high");
  return p !== 0 ? p : a.nextMeeting.localeCompare(b.nextMeeting);
}

interface Props {
  items: InboxItem[] | null | undefined;
  eyebrow: string;
  title: string;
  subtitle?: string;
  listTitle: string;
  openTo: (i: InboxItem) => string;
  onOpen?: (i: InboxItem) => void;
  openedNote: string;
  highNote: string;
  /** Show Open / Finished / All filter above the list (default off). */
  showFilter?: boolean;
  finishedLabel?: string;
  /** Show a dedicated "Request type" column (kind badge) between Client and Priority (default off). */
  kindColumn?: boolean;
  /** Opt-in: show the shared welcome banner at the top (replaces the page header). */
  welcomeRole?: Role;
  /** Opt-in: requests already handled, shown in a separate "Completed" section below the open list. */
  completed?: InboxItem[];
}

export default function InboxList({ items, eyebrow, title, subtitle, listTitle, openTo, onOpen, openedNote, highNote, showFilter, finishedLabel = "Finished", kindColumn = false, welcomeRole, completed }: Props) {
  const cols = kindColumn ? COLS_KIND : COLS;
  const [leastFirst, setLeastFirst] = useState(false);
  const [filter, setFilter] = useState<"open" | "finished" | "all">("open");
  if (!items) return <Loading />;
  const openItems = items.filter((i) => !i.finished);
  const high = openItems.filter((i) => i.priority === "high").length;
  const shown = !showFilter ? items : filter === "all" ? items : items.filter((i) => (filter === "finished") === !!i.finished);
  const sorted = [...shown].sort((a, b) => (leastFirst ? -byUrgency(a, b) : byUrgency(a, b)));

  return (
    <div>
      {welcomeRole ? <WelcomeBanner role={welcomeRole} /> : <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} />}
      <div className="mb-14 grid gap-8 md:grid-cols-2">
        <StatCard icon={Inbox} label="Open requests" value={openItems.length} note={openedNote} />
        <StatCard icon={AlertTriangle} label="High priority" value={high} note={highNote} />
      </div>

      {showFilter && (
        <div className="mb-6 flex flex-wrap items-center gap-2" role="group" aria-label="Filter requests">
          {([["open", "Open"], ["finished", "Finished"], ["all", "All"]] as const).map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}
              className={`cursor-pointer rounded-full px-5 py-2 text-sm font-semibold ${filter === k ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{label}</button>
          ))}
        </div>
      )}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl">{listTitle}</h2>
        <div className="flex items-center gap-2" role="group" aria-label="Sort by urgency">
          <span className="mr-2 text-sm text-ink-muted">Sort by</span>
          {([[false, ArrowUpNarrowWide, "Most urgent first"], [true, ArrowDownWideNarrow, "Least urgent first"]] as const).map(([flag, Icon, label]) => (
            <button key={label} type="button" aria-label={label} title={label} aria-pressed={leastFirst === flag} onClick={() => setLeastFirst(flag)}
              className={`inline-flex h-10 w-10 items-center justify-center rounded-sm border border-ink transition ${leastFirst === flag ? "bg-surface-inverse text-ink-inverse" : "bg-transparent text-ink hover:bg-surface-300"}`}>
              <Icon size={18} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>

      <div className={`hidden px-8 pb-3 text-sm text-ink-muted md:grid ${cols}`}>
        <span>Client</span>{kindColumn && <span>Request type</span>}<span>Priority</span><span>Next meeting</span><span className="invisible">Open</span>
      </div>
      <div className="flex flex-col gap-4">
        {sorted.map((i) => (
          <Card key={i.id} className={`grid gap-y-4 !px-8 !py-6 ${cols}`}>
            <div className="flex flex-wrap items-center gap-3"><p className="text-xl text-ink">{i.clientName}</p>{i.finished && <Badge tone="green">{finishedLabel}</Badge>}{!kindColumn && i.kind && <Badge tone="grey">{i.kind}</Badge>}</div>
            {kindColumn && <div>{i.kind && <Badge tone="grey">{i.kind}</Badge>}</div>}
            <div className="whitespace-nowrap"><Badge tone={i.priority === "high" ? "amber" : "grey"}>{i.priority === "high" ? "High priority" : "Normal"}</Badge></div>
            <p className="text-sm font-semibold">{fmtDate(i.nextMeeting)}</p>
            <div><Link to={openTo(i)} onClick={() => onOpen?.(i)} className="inline-flex min-h-12 items-center rounded-sm bg-brand px-6 text-[15px] font-semibold text-on-brand transition hover:bg-brand-hover">Open</Link></div>
          </Card>
        ))}
        {sorted.length === 0 && <Card><p className="text-ink-500">No requests waiting. New ones appear here as soon as they are sent.</p></Card>}
      </div>

      {completed && completed.length > 0 && (
        <section className="mt-16 border-t border-hairline pt-10" aria-label="Completed requests">
          <div className="mb-6 flex flex-wrap items-center gap-3"><h2 className="text-2xl">Completed</h2><Badge tone="green">{completed.length}</Badge></div>
          <div className="flex flex-col gap-4">
            {[...completed].sort(byUrgency).map((i) => (
              <Card key={i.id} className={`grid gap-y-4 !px-8 !py-6 ${cols}`}>
                <div className="flex flex-wrap items-center gap-3"><p className="text-xl text-ink">{i.clientName}</p><Badge tone="green">Completed</Badge>{!kindColumn && i.kind && <Badge tone="grey">{i.kind}</Badge>}</div>
                {kindColumn && <div>{i.kind && <Badge tone="grey">{i.kind}</Badge>}</div>}
                <div className="whitespace-nowrap"><Badge tone="grey">Returned to RM</Badge></div>
                <p className="text-sm font-semibold">{fmtDate(i.nextMeeting)}</p>
                <div><Link to={openTo(i)} onClick={() => onOpen?.(i)} className="inline-flex min-h-12 items-center rounded-sm border border-ink px-6 text-[15px] font-semibold text-ink transition hover:bg-surface-300">View</Link></div>
              </Card>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
