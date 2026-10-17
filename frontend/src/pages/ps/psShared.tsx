import { Link, useLocation } from "react-router-dom";
import type { Client, MarketRow } from "../../types/arc";

const key = (clientId: string) => `ps-selection-${clientId}`;

/** Session-scoped store so the research chat and Finalise agree on the ticked products. */
export function loadSelection(clientId: string): MarketRow[] {
  try {
    const raw = sessionStorage.getItem(key(clientId));
    return raw ? (JSON.parse(raw) as MarketRow[]) : [];
  } catch { return []; }
}
export function saveSelection(clientId: string, rows: MarketRow[]) {
  try { sessionStorage.setItem(key(clientId), JSON.stringify(rows)); } catch { /* ignore */ }
}

export const PS_STEPS = [{ label: "Product & Market Research" }, { label: "Send To IC" }];

export function ClientStrip({ client }: { client?: Client }) {
  const { pathname } = useLocation();
  if (!client) return null;
  return (
    <div className="mb-12 flex flex-wrap items-center gap-x-10 gap-y-3 rounded-lg border border-ink-200 bg-surface-100 px-7 py-4 text-sm">
      <span className="font-semibold text-ink">{client.name}</span>
      <span className="text-ink-700">Risk limit: {client.riskCap} of 5 ({client.riskCategory})</span>
      <span className="text-ink-700">IPS {client.ipsVersion ? `v${client.ipsVersion}` : "not yet issued"}</span>
      <Link to={`/ps/clients/${client.id}`} state={{ from: pathname, fromLabel: "Back To AI Assistant" }} className="ml-auto font-semibold text-ink underline">View client overview</Link>
    </div>
  );
}
