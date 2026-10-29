import type { IpsNoteRef } from "../../../types/arc";

/** IPS structured fields (align with backend IPS JSON: goals, targets, reviewRules). Read tolerantly. */
export interface IpsTarget { id?: string; amount?: string | number; currency?: string; horizonYears?: number; text: string; source_note?: IpsNoteRef | string | null }
export interface ReviewRule { title: string; text: string }

export const targetLine = (t: IpsTarget): string => {
  if (t.text?.trim()) return t.text;
  const amt = t.amount != null && t.amount !== "" ? `${t.currency ?? "SGD"} ${t.amount}` : "";
  return [amt, t.horizonYears ? `in ${t.horizonYears} years` : ""].filter(Boolean).join(" ");
};

/** "Title, 2026-10-20" for a backend source_note ({id,date,title}) or a plain string. */
export const noteLabel = (n: IpsNoteRef | string | null | undefined): string =>
  !n ? "" : typeof n === "string" ? n : [n.title ?? n.id, n.date].filter(Boolean).join(", ");
