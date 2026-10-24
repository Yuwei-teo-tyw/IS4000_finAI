import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import type { Role } from "../types/arc";
import ThemeToggle from "./ThemeToggle";
import SettingsDialog from "../components/settings/SettingsDialog";
import { ROLE_PEOPLE, getNav, useActiveClientId } from "./navConfig";

const ROLES: Role[] = ["rm", "ps", "pm"];
const LABEL = "mb-2 px-2 text-[12px] font-medium text-ink-muted max-md:hidden";

export default function Sidebar({ role }: { role: Role }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const current = ROLES.find((r) => pathname === `/${r}` || pathname.startsWith(`/${r}/`)) ?? role;
  const clientId = useActiveClientId();
  const nav = getNav(role, clientId);

  return (
    <aside className="print:hidden sticky top-0 flex h-screen w-[76px] shrink-0 flex-col gap-8 overflow-y-auto border-r border-hairline bg-surface-200 px-[14px] py-5 md:w-56">
      <Link to="/rm/clients" aria-label="Geneva home" className="flex items-center gap-3 px-2 max-md:justify-center max-md:px-0">
        <img src="/ubs-logo.png" alt="UBS" className="ubs-logo h-10 w-auto" />
        <span className="text-[24px] font-medium leading-none text-ink max-md:hidden">Geneva</span>
      </Link>

      <section>
        <div className={LABEL}>Working As</div>
        <div className="flex flex-col gap-1">
          {ROLES.map((r) => {
            const active = r === current;
            const p = ROLE_PEOPLE[r];
            return (
              <button key={r} type="button" aria-pressed={active} aria-current={active ? "true" : undefined} title={`${p.name} (${p.person})`}
                onClick={() => navigate(p.home)}
                className={`flex w-full items-center gap-3 rounded-sm border p-2 text-left max-md:justify-center ${active ? "border-ink bg-surface-100 shadow-card" : "border-transparent hover:bg-surface-300"}`}>
                <span className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-sm text-[12px] font-medium ${active ? "bg-brand text-on-brand" : "bg-surface-300 text-ink"}`}>
                  {r.toUpperCase()}
                </span>
                <span className="min-w-0 max-md:hidden">
                  <span className="block text-[13.5px] font-medium leading-5 text-ink">{p.name}</span>
                  <span className="block text-[12px] leading-4 text-ink-muted">{p.person}</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section>
        <div className={LABEL}>Workspace</div>
        <nav className="flex flex-col gap-1">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} title={label}
              className={({ isActive }) => `flex min-h-11 items-center gap-3 rounded-sm border-l-[3px] px-3 text-[14.5px] max-md:justify-center max-md:px-0 ${isActive ? "border-brand bg-surface-100 font-medium text-ink shadow-card" : "border-transparent text-ink hover:bg-surface-300"}`}>
              <Icon size={18} strokeWidth={1.5} className="shrink-0 text-ink-muted" aria-hidden />
              <span className="max-md:sr-only">{label}</span>
            </NavLink>
          ))}
        </nav>
      </section>

      <footer className="mt-auto flex flex-col gap-3">
        <ThemeToggle />
        <SettingsDialog role={role} />
        <p className="px-2 text-[11.5px] leading-4 text-ink-muted max-md:hidden">Research Prototype. Synthetic Data Only.</p>
      </footer>
    </aside>
  );
}
