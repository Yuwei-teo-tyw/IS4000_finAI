import type { IpsNoteRef } from "../../../types/arc";

/** IPS structured fields (align with backend IPS JSON: goals, targets, lifeEvents, reviewRules). Read tolerantly. */
export interface IpsTarget { id?: string; amount?: string | number; currency?: string; horizonYears?: number; text: string; source_note?: IpsNoteRef | string | null }
export interface IpsLifeEvent { id: string; year?: number | string; date?: string; label: string; detail?: string; source_note?: IpsNoteRef | string | null; manual?: boolean }
export interface ReviewRule { title: string; text: string }

/** Tolerant normaliser for lifeEvents coming from the backend or the store. */
export function normaliseLifeEvents(raw: unknown): IpsLifeEvent[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((r, i): IpsLifeEvent[] => {
    const o = r as Partial<IpsLifeEvent> | null;
    if (!o || typeof o.label !== "string" || !o.label.trim()) return [];
    return [{ ...o, label: o.label, id: o.id ?? `ev-${i}-${o.label}` }];
  });
}

/** Sort key: ISO date or year -> number (undated last). */
export function eventTime(e: IpsLifeEvent): number {
  if (e.date) { const t = Date.parse(e.date); if (!Number.isNaN(t)) return t; }
  const y = Number(e.year);
  return Number.isFinite(y) && y > 0 ? Date.UTC(y, 0, 1) : Number.MAX_SAFE_INTEGER;
}

export function eventWhen(e: IpsLifeEvent): string {
  if (e.date) {
    const t = Date.parse(e.date);
    if (!Number.isNaN(t)) return /^\d{4}-\d{2}-\d{2}/.test(e.date) ? new Date(t).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" }) : String(new Date(t).getFullYear());
    return e.date;
  }
  return e.year != null ? String(e.year) : "";
}

export const targetLine = (t: IpsTarget): string => {
  if (t.text?.trim()) return t.text;
  const amt = t.amount != null && t.amount !== "" ? `${t.currency ?? "SGD"} ${t.amount}` : "";
  return [amt, t.horizonYears ? `in ${t.horizonYears} years` : ""].filter(Boolean).join(" ");
};

/** "Title, 2026-10-20" for a backend source_note ({id,date,title}) or a plain string. */
export const noteLabel = (n: IpsNoteRef | string | null | undefined): string =>
  !n ? "" : typeof n === "string" ? n : [n.title ?? n.id, n.date].filter(Boolean).join(", ");
