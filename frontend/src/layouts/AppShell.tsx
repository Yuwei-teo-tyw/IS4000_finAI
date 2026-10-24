import { Outlet, useLocation } from "react-router-dom";
import type { Role } from "../types/arc";
import Sidebar from "./Sidebar";
import { useActiveClientId } from "./navConfig";
import GenevaLauncher from "../components/geneva/GenevaLauncher";

/** Routes are literal /rm, /pm, /ps (no :role param), so read the role from the URL. */
export function useRole(): Role {
  const seg = useLocation().pathname.split("/")[1];
  return (seg === "pm" || seg === "ps" ? seg : "rm") as Role;
}

/** Lux shell: left sidebar (role switcher + workspace nav) and a spacious content column. */
export default function AppShell() {
  const role = useRole();
  const clientId = useActiveClientId();
  const { pathname, search } = useLocation();
  const onAssistant = /\/assistant$/.test(pathname);
  const tab = new URLSearchParams(search).get("tab");
  // PS keeps the docked chat on every assistant tab except the research chat.
  const inPageChat = onAssistant && !(role === "ps" && tab && tab !== "research");
  return (
    <div className="arc flex h-screen overflow-hidden bg-surface-100 print:block print:h-auto print:overflow-visible">
      <Sidebar role={role} />
      <main className="min-w-0 flex-1 overflow-y-auto px-6 py-12 md:px-10 print:block print:h-auto print:overflow-visible print:p-0">
        <div className="mx-auto w-full max-w-[1760px] print:max-w-none">
          <Outlet />
        </div>
      </main>
      {!inPageChat && <GenevaLauncher role={role} clientId={clientId} />}
    </div>
  );
}
