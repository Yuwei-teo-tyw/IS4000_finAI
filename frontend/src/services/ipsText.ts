import type { Philosophy } from "../types/arc";

const clean = (t?: string) => (t ?? "").trim().replace(/[.\s]+$/, "");
/** Composes the investment philosophy sentence from whichever blanks are filled; "" when none. */
export function philosophySentence(p: Philosophy): string {
  const a = clean(p.approach), b = clean(p.believes), c = clean(p.avoids);
  const head = [a && `prefers a ${a} investing approach`, b && `believes in ${b} kinds of companies and industries`].filter(Boolean).join(", and ");
  if (!head && !c) return "";
  const tail = c ? `${head ? ", but " : ""}steers away from ${c}` : "";
  return `The client ${head}${tail}.`;
}
