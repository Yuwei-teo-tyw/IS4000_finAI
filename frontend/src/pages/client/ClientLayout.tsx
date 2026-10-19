import { NavLink, Outlet, Link, useLocation } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useRole } from "../../layouts/AppShell";
import { Badge, Loading, RiskScale, sgd } from "../../components/ui";
import { fmtDate } from "../rm/rmShared";
import { useNotifications, markRead } from "../../services/notificationStore";
import { useClient } from "../../components/client/useClient";

const TABS = [
  { to: "", label: "Overview", end: true, rmOnly: false },
  { to: "documents", label: "IPS", end: false, rmOnly: false },
  { to: "upload-notes", label: "Meeting Notes", end: false, rmOnly: true },
  { to: "review-pack", label: "Review Pack", end: false, rmOnly: true, kind: "pack" as const },
  { to: "ips-creation", label: "IPS creation", end: false, rmOnly: true, kind: "ips" as const },
];
const BACK = { rm: ["clients", "Back to Client Book"], ic: ["inbox", "Back to Inbox"], ps: ["inbox", "Back to Inbox"] } as const;
export default function ClientLayout() {
  const role = useRole();
  const { state } = useLocation() as { state: { from?: string; fromLabel?: string } | null };
  const { clientId, client } = useClient();
  const unread = useNotifications(role).filter((n) => n.clientId === clientId);
  if (!client) return <Loading />;
  const [backTo, backLabel] = BACK[role];
  return (
    <div>
      <Link to={state?.from ?? `/${role}/${backTo}`} className="mb-8 inline-flex items-center gap-2 text-sm font-semibold text-ink hover:text-ink-muted">
        <ArrowLeft size={16} /> {state?.from ? state.fromLabel ?? "Back" : backLabel}
      </Link>
      <header className="mb-8 rounded-lg bg-surface-100 p-8 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-muted">Client 360</p>
            <h1 className="mt-1 text-4xl font-light">{client.name}</h1>
          </div>
        </div>
        <div className="mt-8 flex flex-wrap items-center gap-x-10 gap-y-4 text-sm text-ink-700">
          <span className="inline-flex items-center gap-3">Risk <RiskScale value={client.riskCap} /></span>
          <span>AUM <strong className="text-ink">{sgd(client.aumSgd)}</strong></span>
          <span className="inline-flex items-center gap-2">Phase <Badge tone="grey"><span className="whitespace-nowrap">{client.status}</span></Badge></span>
          <Badge tone="grey">Next Meeting {fmtDate(client.nextMeeting)}</Badge>
        </div>
      </header>
      <nav className="mb-10 flex flex-wrap gap-2 border-b border-ink-200">
        {TABS.filter((t) => !t.rmOnly || role === "rm").map((t) => (
          <NavLink key={t.label} to={`/${role}/clients/${clientId}/${t.to}`} end={t.end} state={state}
            onClick={() => { if ("kind" in t) unread.filter((n) => n.kind === t.kind).forEach((n) => markRead(n.id)); }}
            className={({ isActive }) => `-mb-px border-b-2 px-5 py-3 text-sm font-semibold ${isActive ? "border-hairline-strong text-ink" : "border-transparent text-ink-500 hover:text-ink"}`}>
            {t.label}
            {"kind" in t && unread.some((n) => n.kind === t.kind) && <span className="ml-2 inline-block h-2 w-2 rounded-full bg-brand align-middle" aria-label="New hand-over" />}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
