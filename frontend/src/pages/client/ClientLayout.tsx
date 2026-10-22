import { NavLink, Navigate, Outlet, Link, useLocation } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useRole } from "../../layouts/AppShell";
import { Badge, Loading, RiskScale, sgd } from "../../components/ui";
import { fmtDate } from "../rm/rmShared";
import { useClient } from "../../components/client/useClient";

const TABS = [
  { to: "", label: "Overview", end: true, rmOnly: false },
  { to: "upload-notes", label: "Meeting Notes", end: false, rmOnly: true },
  { to: "documents", label: "IPS", end: false, rmOnly: false },
  { to: "review-pack", label: "Review Pack", end: false, rmOnly: true },
];
const BACK = { rm: ["clients", "Back to Client Book"], pm: ["inbox", "Back to Inbox"], ps: ["inbox", "Back to Inbox"] } as const;
export default function ClientLayout() {
  const role = useRole();
  const { state, pathname } = useLocation() as { state: { from?: string; fromLabel?: string } | null; pathname: string };
  const { clientId, client } = useClient();
  if (!client) return <Loading />;
  const [backTo, backLabel] = BACK[role];
  const onboarding = client.status === "Onboarding Phase";
  if (onboarding && /\/review-pack\/?$/.test(pathname)) return <Navigate to={`/${role}/clients/${clientId}/`} replace />;
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
        {TABS.filter((t) => !t.rmOnly || role === "rm").map((t) => t.to === "review-pack" && onboarding ? (
          <span key={t.label} aria-disabled="true" title="Onboarding and IPS not completed"
            className="-mb-px cursor-not-allowed border-b-2 border-transparent px-5 py-3 text-sm font-semibold text-ink-muted opacity-50">{t.label}</span>
        ) : (
          <NavLink key={t.label} to={`/${role}/clients/${clientId}/${t.to}`} end={t.end} state={state}
            className={({ isActive }) => `-mb-px border-b-2 px-5 py-3 text-sm font-semibold ${isActive ? "border-hairline-strong text-ink" : "border-transparent text-ink-500 hover:text-ink"}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
