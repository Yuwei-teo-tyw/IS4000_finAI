/** Pure bullet helpers (no React). Shared by ui/BulletText, arcApi and document parts. */
const B = "• ";
const MARK = /^\s*[•\-*]\s*/;

export interface BulletOptions {
  /** Also split unmarked prose on ";" followed by a new sentence. */
  splitSemicolon?: boolean;
  /** Remove one trailing period from each item. */
  stripPeriod?: boolean;
}

/** Normalise any text to clean items: strip markers per line, split unmarked prose into sentences, drop empties. */
export function toBulletItems(text: string, opts: BulletOptions = {}): string[] {
  const split = opts.splitSemicolon ? /(?<=[.!?;](?:\s*\[[A-Za-z0-9-]+\])*)\s+(?=[A-Z0-9])/ : /(?<=[.!?](?:\s*\[[A-Za-z0-9-]+\])*)\s+(?=[A-Z0-9])/;
  const out: string[] = [];
  for (const raw of (text ?? "").split(/\r?\n/)) {
    const marked = MARK.test(raw);
    const line = raw.replace(MARK, "").trim();
    if (!line) continue;
    const parts = marked ? [line] : line.split(split);
    for (const p of parts) {
      let t = p.trim().replace(MARK, "").trim();
      if (opts.stripPeriod) t = t.replace(/\.$/, "");
      if (t) out.push(t);
    }
  }
  return out;
}

/** Join already-clean items as "• a\n• b" without re-splitting them. */
export const bulletLines = (items: string[]): string => items.map((i) => B + i).join("\n");

/** "• a\n• b" */
export function toBulletText(text: string): string {
  return bulletLines(toBulletItems(text));
}
