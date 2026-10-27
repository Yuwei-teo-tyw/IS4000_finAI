import { useCallback, useEffect, useState } from "react";
import { arcApi, type IpsSendStatus } from "../../services/arcApi";
import { parseGoals } from "../../components/documents/ips/goals";
import type { ThreeLProportion } from "../../types/arc";

/** "27 Oct 2026, 20:15" */
export function formatSentAt(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

export type IpsStatusLabel = "Draft" | "Sent to PM" | "Returned by PM";

/** Backend send status for the client, re-fetched on demand. `null` while loading or when the backend cannot be reached. */
export function useIpsSendStatus(clientId: string): { status: IpsSendStatus | null; refresh: () => Promise<void> } {
  const [status, setStatus] = useState<IpsSendStatus | null>(null);
  const refresh = useCallback(async () => {
    try { setStatus(await arcApi.getIpsSendStatus(clientId)); } catch { setStatus(null); }
  }, [clientId]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { status, refresh };
}

/** Sections of the IPS that still read "Not yet completed", from the current editor state. */
export function findEmptySections(s: {
  text: Record<number, string>; targetsCount: number; philosophy: { approach?: string; believes?: string; avoids?: string; statement?: string; investmentPeriod?: string };
  risk: Record<string, string>; proportion: ThreeLProportion | null; allocation: { liquidity?: string; longevity?: string; legacy?: string };
}): string[] {
  const out: string[] = [];
  for (const g of parseGoals(s.text[1] ?? "")) if (!g.bullets.length) out.push(`Goals: ${g.title}`);
  if (!s.targetsCount) out.push("Targets");
  const p = s.philosophy;
  if (!(p.statement?.trim() || p.approach?.trim() || p.believes?.trim() || p.avoids?.trim())) out.push("Investment philosophy");
  if (!p.investmentPeriod?.trim()) out.push("Investment period");
  if (!Object.values(s.risk).some((v) => v?.trim()) && !(s.text[3] ?? "").trim()) out.push("Risk profile");
  if (!s.proportion) out.push("3L proportion");
  for (const b of ["liquidity", "longevity", "legacy"] as const) if (!s.allocation[b]) out.push(`3L strategy: ${b[0].toUpperCase()}${b.slice(1)}`);
  return out;
}
