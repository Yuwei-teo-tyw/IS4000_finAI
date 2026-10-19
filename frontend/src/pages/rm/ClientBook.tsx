import { useState } from "react";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, CalendarClock, Landmark, Users, type LucideIcon } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, Loading, RiskScale, sgd, useAsync } from "../../components/ui";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useRole } from "../../layouts/AppShell";
import { fmtDate, usePackStatus } from "./rmShared";
import { useActivated, useIpsReturned, useIpsSent } from "../../services/workflowStore";

const TODAY = new Date("2026-10-17");
const DAY = 86_400_000;
const COLS = "md:grid-cols-[1.4fr_1fr_0.8fr_1.1fr_1.1fr_auto] md:items-center md:gap-x-8";
const COLS_RM = "md:grid-cols-[1.3fr_1fr_0.8fr_1fr_1fr_1.1fr_1.1fr_auto] md:items-center md:gap-x-6";

const TAGLINES = [
  "Great relationships are built one thoughtful conversation at a time.",
  "Trust is the quiet foundation of every portfolio.",
  "Today, someone's long-term plan is in good hands.",
  "Listen first. The numbers will follow.",
  "Wealth is a means; your clients' stories are the purpose.",
  "Small moments of care compound like capital.",
  "Clarity for them, calm for you.",
  "Every goal begins with a conversation.",
  "Steady guidance through every market season.",
  "Behind each portfolio is a family's future.",
  "Patience, preparation, and a good question.",
  "Make today's meeting count.",
  "Advice earns trust; trust earns a lifetime of partnership.",
  "The best plans are the ones clients understand and believe in.",
];

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
      <div className="h-1 w-full bg-hairline" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={label}>
        <div className="h-full bg-brand" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
      </div>
      <p className="mt-2 text-xs text-ink-muted">{done >= total && total > 0 ? "Complete" : `${done} of ${total}`}</p>
    </div>
  );
}

/** RM-only progress cells. Onboarding: notes, IPS draft, sent to IC, returned, active. Pack: sections complete. */
function ProgressCells({ clientId, monitoring }: { clientId: string; monitoring: boolean }) {
  const sent = !!useIpsSent(clientId);
  const returned = useIpsReturned(clientId);
  const active = useActivated(clientId);
  const pack = usePackStatus(clientId);
  const step = monitoring || active ? 5 : returned ? 4 : sent ? 3 : 2;
  const onboarding = monitoring || active
    ? <Bar done={5} total={5} label="Onboarding progress" />
    : <Bar done={step} total={5} label="Onboarding progress" />;
  const packCell = !(monitoring || active)
    ? <p className="text-xs text-ink-muted">Not started</p>
    : pack.ready ? <Bar done={pack.doneCount} total={pack.total} label="Review pack progress" /> : <p className="text-xs text-ink-muted">Loading</p>;
  return <>{onboarding}{packCell}</>;
}

export default function ClientBook() {
  const role = useRole();
  const isRm = role === "rm";
  const clients = useAsync(() => arcApi.listClients());
  const [furthestFirst, setFurthestFirst] = useState(false);
  const [tagline] = useState(() => TAGLINES[Math.floor(Math.random() * TAGLINES.length)]);
  if (!clients) return <Loading />;
  const total = clients.reduce((a, c) => a + c.aumSgd, 0);
  const sorted = [...clients].sort((a, b) => {
    const diff = new Date(a.nextMeeting).getTime() - new Date(b.nextMeeting).getTime();
    return furthestFirst ? -diff : diff;
  });
  const onboarding = sorted.filter((c) => c.status.startsWith("Onboarding"));
  const monitoring = sorted.filter((c) => !c.status.startsWith("Onboarding"));
  const groups = [{ title: "Onboarding", list: onboarding }, { title: "Monitoring", list: monitoring }].filter((g) => g.list.length);
  const earliest = [...clients].sort((a, b) => a.nextMeeting.localeCompare(b.nextMeeting))[0]?.nextMeeting;

  return (
    <div>
      <section
        className="mb-14 flex min-h-44 items-center rounded-lg bg-cover bg-center p-6 md:px-10"
        style={{ backgroundImage: "url(/hero-banner.png), linear-gradient(135deg, #d9d6cc 0%, #b9b6ab 100%)" }}
      >
        <div className="max-w-md rounded-sm bg-[rgb(255_255_255/0.92)] p-5 text-[#1c1c1c] shadow-card">
          <div className="border-l-[3px] border-brand pl-5">
            <h1 className="text-2xl font-light leading-tight">Welcome back, {ROLE_PEOPLE[role].person}</h1>
            <p className="mt-2 text-sm font-light text-[#3a3a3a]">{tagline}</p>
          </div>
        </div>
      </section>

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

      <div className={`hidden px-8 pb-3 text-sm text-ink-muted md:grid ${isRm ? COLS_RM : COLS}`}>
        <span>Client</span><span>Risk appetite</span><span>AUM</span><span>Phase</span><span>Next Meeting</span>{isRm && <><span>Onboarding progress</span><span>Review pack progress</span></>}<span className="invisible">Open</span>
      </div>
      <div className="flex flex-col gap-10">
        {groups.map((g) => (
          <section key={g.title} aria-label={`${g.title} clients`}>
            <h3 className="mb-4 text-lg">{g.title} <span className="text-ink-muted">({g.list.length})</span></h3>
            <div className="flex flex-col gap-4">
        {g.list.map((c) => (
          <Card key={c.id} className={`grid gap-y-4 !px-8 !py-6 ${isRm ? COLS_RM : COLS}`}>
            <p className="text-xl text-ink">{c.name}</p>
            <div><RiskScale value={c.riskCap} /><p className="mt-2 text-xs text-ink-muted">{c.riskCategory}, {c.riskCap} of 5</p></div>
            <p className="text-sm font-semibold">{sgd(c.aumSgd)}</p>
            <div className="whitespace-nowrap"><Badge tone="grey"><span className="whitespace-nowrap">{c.status}</span></Badge></div>
            <div className="text-sm">
              <p className="font-semibold">{fmtDate(c.nextMeeting)}</p>
              <p className="mt-1 text-ink-muted">{relative(c.nextMeeting)}</p>
            </div>
            {isRm && <ProgressCells clientId={c.id} monitoring={g.title === "Monitoring"} />}
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
