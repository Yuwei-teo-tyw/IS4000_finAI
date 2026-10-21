/** Product-name matching for chat text ("finalise the global quality dividend ETF and the SGD bill fund"). */
const STOP = new Set(["the", "and", "fund", "funds", "etf", "etfs", "of", "a", "an", "for", "fixed", "income", "plc", "ltd", "inc", "note", "class", "illustrative", "sgd", "usd", "hedged"]);
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
const stem = (w: string) => w.replace(/s$/, "");
/** The name as people say it: without the "Illustrative" prefix and any "(SGD-Hedged)" style suffix. */
const core = (name: string) => norm(name.replace(/^illustrative\s+/i, "").replace(/\([^)]*\)/g, ""));

/** Product matches when its id or full name appears, or most of its distinctive words do (at least two, or its only one). */
export function matchesProduct(text: string, name: string, id?: string): boolean {
  const t = norm(text), n = norm(name);
  if (t.includes(n) || t.includes(core(name)) || (id && t.includes(norm(id)))) return true;
  const words = new Set(t.split(" ").map(stem));
  const sig = n.split(" ").filter((w) => !STOP.has(w));
  if (sig.length === 0) return false;
  const hit = sig.filter((w) => words.has(stem(w))).length;
  return sig.length === 1 ? hit === 1 : hit >= 2 && hit / sig.length >= 0.6;
}

/**
 * The items the text names. Exact mentions (id, full name or the name without "Illustrative"/suffix) win;
 * the loose word match is used only when nothing is named exactly, so "Global Equity Index ETF" does not
 * also pick up the "Singapore Equity Index ETF".
 */
export function findProducts<T>(text: string, items: T[], name: (x: T) => string, id?: (x: T) => string): T[] {
  const t = norm(text);
  const exact = items.filter((x) => t.includes(core(name(x))) || t.includes(norm(name(x))) || (id && t.includes(norm(id(x)))));
  return exact.length ? exact : items.filter((x) => matchesProduct(text, name(x), id?.(x)));
}
