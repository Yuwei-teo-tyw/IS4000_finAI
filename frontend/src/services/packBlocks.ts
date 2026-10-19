import { toBulletItems } from "../utils/bullets";

/** Pack section body contract: blocks separated by a blank line, each `## Heading` then its bullet lines. */
export type TextBlock = { heading?: string; text: string };

const HEADING = /^\s*##\s+(.*\S)\s*$/;
const asBullets = (lines: string) => toBulletItems(lines).map((i) => `• ${i}`).join("\n");

/** True when the text uses `## Heading` lines. */
export const hasHeadings = (text: string): boolean => /^\s*##\s+\S/m.test(text ?? "");

/** Splits `## Heading` + bullet blocks. Text without a heading is kept as one headless block. */
export function parseBlocks(text: string): TextBlock[] {
  const blocks: TextBlock[] = [];
  let cur: { heading?: string; lines: string[] } | null = null;
  const flush = () => {
    if (cur) {
      const body = asBullets(cur.lines.join("\n"));
      if (cur.heading || body) blocks.push(cur.heading ? { heading: cur.heading, text: body } : { text: body });
    }
    cur = null;
  };
  for (const raw of (text ?? "").split(/\r?\n/)) {
    const h = raw.match(HEADING);
    if (h) { flush(); cur = { heading: h[1], lines: [] }; continue; }
    if (!cur) cur = { lines: [] };
    cur.lines.push(raw);
  }
  flush();
  return blocks;
}

/** Inverse of parseBlocks: `## Heading\n• ...` joined by a blank line. */
export function composeBlocks(pairs: [string, string][]): string {
  return pairs.map(([h, t]) => `## ${h}\n${asBullets(t)}`).join("\n\n");
}
