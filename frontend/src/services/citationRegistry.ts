/** Lookup of what a citation id points to (title, date, verbatim passage, link). Filled by whatever loads sources (review pack, IPS generation, notes); read by CitationTag. */
const API = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
export interface CitationInfo { id: string; title?: string; date?: string; passage?: string; url?: string; route?: string; note?: string }

const reg = new Map<string, CitationInfo>();
const subs = new Set<() => void>();
let ver = 0;
const key = (id: string) => id.trim().toLowerCase();

/** Add or merge source details; later calls only fill fields that are present. */
export function registerCitations(list: Array<Partial<CitationInfo> & { id?: string }> | undefined | null) {
  let changed = false;
  for (const c of list ?? []) {
    if (!c?.id) continue;
    const prev = reg.get(key(c.id));
    const next: CitationInfo = { ...prev, id: c.id };
    for (const k of ["title", "date", "passage", "url", "route", "note"] as const) if (c[k]) { if (next[k] !== c[k]) changed = true; next[k] = c[k]; }
    if (!prev) changed = true;
    reg.set(key(c.id), next);
  }
  if (changed) { ver++; subs.forEach((f) => f()); }
}
export const subscribeCitations = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export const citationVersion = () => ver;

/** Registered details, else what the id itself tells us (FRED series, house-view page), else null. */
export function lookupCitation(id: string): CitationInfo | null {
  const hit = reg.get(key(id));
  if (hit && (hit.title || hit.passage || hit.date || hit.url || hit.route)) return hit;
  const hv = /^HV-(\d{4})-(\d{2})(?:-p(\d+))?$/i.exec(id);
  if (hv) return { id, title: "CIO house view", date: `${hv[1]}-${hv[2]}`, url: `${API}/agents/product-recommender/house-view/document${hv[3] ? `#page=${hv[3]}` : ""}`, note: hv[3] ? `Page ${hv[3]} of the house view report` : undefined };
  if (/^[A-Z][A-Z0-9]{3,}$/.test(id) && /[A-Z]/.test(id) && !/^(CIO|MKT)/.test(id)) return { id, title: `FRED series ${id}`, url: `https://fred.stlouisfed.org/series/${id}`, note: "Federal Reserve Economic Data series" };
  return null;
}
