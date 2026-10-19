import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, CalendarClock, Landmark, Users, type LucideIcon } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, Loading, RiskScale, sgd, useAsync } from "../../components/ui";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useRole } from "../../layouts/AppShell";
import { markRead, useNotifications } from "../../services/notificationStore";
import { setIpsComplete, setWorkflowComplete, useWorkflowStage } from "../../services/workflowStore";
import type { Client, Role } from "../../types/arc";
import { fmtDate } from "./rmShared";

const TODAY = new Date("2026-10-17");
const DAY = 86_400_000;
const COLS = "md:grid-cols-[1.5fr_1fr_0.8fr_1fr_1.1fr_2fr_auto] md:items-center md:gap-x-8";

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

function StageBar({ clientId, role }: { clientId: string; role: Role }) {
  const { kind, steps, percent } = useWorkflowStage(clientId);
  const complete = percent === 100;
  const allReviewed = !complete && steps.slice(0, -1).every((x) => x.state === "done");
  return (
    <div className="min-w-0" aria-label={`${kind === "ips" ? "IPS" : "Review pack"} workflow ${percent} percent`}>
      <div className="flex items-center gap-3">
        <div className="flex h-1.5 min-w-0 flex-1 gap-0.5" aria-hidden="true">
          {steps.map((st, i) => (
            <span key={i} className={`h-full flex-1 ${st.state === "done" || complete ? "bg-brand" : st.state === "current" ? "bg-brand/30" : "bg-surface-300"}`} />
          ))}
        </div>
        <span className="text-xs text-ink-muted">{percent}%</span>
      </div>
      <div className="mt-2 flex gap-0.5 text-[11px] leading-4 text-ink-muted" aria-hidden="true">
        {steps.map((st, i) => (
          <span key={i} className={`flex-1 truncate ${st.state === "current" && !complete ? "text-ink underline underline-offset-4" : ""}`}>{st.role.toUpperCase()}</span>
        ))}
      </div>
      <p className="mt-1 text-xs text-ink-muted">{complete ? "Complete" : steps.find((x) => x.state === "current")?.label}</p>
      {role === "rm" && allReviewed && (
        <div className="mt-3"><Button size="sm" onClick={() => (kind === "ips" ? setIpsComplete(clientId) : setWorkflowComplete(clientId))}>Complete workflow</Button></div>
      )}
    </div>
  );
}

function ClientRow({ c, role }: { c: Client; role: Role }) {
  const unread = useNotifications(role).filter((n) => n.clientId === c.id);
  const latest = unread[0];
  const open = () => unread.forEach((n) => markRead(n.id));
  return (
    <Card className={`grid gap-y-4 !px-8 !py-6 ${COLS}`}>
      <div className="min-w-0">
        <Link to={`/${role}/clients/${c.id}`} onClick={open} className="text-xl text-ink">{c.name}</Link>
        {latest && (
          <p className="mt-2"><span className="inline-flex items-center gap-2 rounded-sm border border-hairline px-2 py-1 text-xs text-ink">
            <span className="size-2 rounded-full bg-brand" aria-hidden="true" />{latest.kind === "ips" ? "New IPS" : "New Review pack"}
          </span></p>
        )}
      </div>
      <div><RiskScale value={c.riskCap} /><p className="mt-2 text-xs text-ink-muted">{c.riskCategory}, {c.riskCap} of 5</p></div>
      <p className="text-sm font-semibold">{sgd(c.aumSgd)}</p>
      <div className="whitespace-nowrap"><Badge tone="grey"><span className="whitespace-nowrap">{c.status}</span></Badge></div>
      <div className="text-sm">
        <p className="font-semibold">{fmtDate(c.nextMeeting)}</p>
        <p className="mt-1 text-ink-muted">{relative(c.nextMeeting)}</p>
      </div>
      <StageBar clientId={c.id} role={role} />
      <div onClick={open}><Button to={`/${role}/clients/${c.id}`}>Open</Button></div>
    </Card>
  );
}

export default function ClientBook() {
  const role = useRole();
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

      <div className={`hidden px-8 pb-3 text-sm text-ink-muted md:grid ${COLS}`}>
        <span>Client</span><span>Risk appetite</span><span>AUM</span><span>Phase</span><span>Next Meeting</span><span>Stage</span><span className="invisible">Open</span>
      </div>
      <div className="flex flex-col gap-10">
        {groups.map((g) => (
          <section key={g.title} aria-label={`${g.title} clients`}>
            <h3 className="mb-4 text-lg">{g.title} <span className="text-ink-muted">({g.list.length})</span></h3>
            <div className="flex flex-col gap-4">
        {g.list.map((c) => <ClientRow key={c.id} c={c} role={role} />)}
      </div>
          </section>
        ))}
      </div>
    </div>
  );
}
