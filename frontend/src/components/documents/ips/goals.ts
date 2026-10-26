import { toBullets } from "./parts";

export const GOAL_SECTIONS = [
  { key: "return", title: "Return Requirements" },
  { key: "horizon", title: "Investment Time Horizon" },
  { key: "primary", title: "Primary Goals" },
  { key: "secondary", title: "Secondary Goals" },
  { key: "liquidity", title: "Liquidity Needs" },
  { key: "tax", title: "Tax Considerations" },
  { key: "unique", title: "Unique Circumstances and Preferences" },
] as const;
export type GoalKey = (typeof GOAL_SECTIONS)[number]["key"];
export interface GoalGroup { key: GoalKey; title: string; bullets: string[] }

const ALIASES: [RegExp, GoalKey][] = [
  [/^return/i, "return"], [/horizon/i, "horizon"], [/^primary/i, "primary"], [/^secondary/i, "secondary"],
  [/liquidity/i, "liquidity"], [/^tax/i, "tax"], [/^unique|circumstance|preference/i, "unique"],
];
const LABEL = /^([A-Z][A-Za-z &/()'-]{1,48}):\s+(\S[\s\S]*)$/;
const keyFor = (label: string): GoalKey | undefined => {
  const exact = GOAL_SECTIONS.find((s) => s.title.toLowerCase() === label.toLowerCase());
  return exact?.key ?? ALIASES.find(([re]) => re.test(label))?.[1];
};

/** Part-1 body ("Heading: bullet" lines) -> the 7 fixed sections in order (always all 7). Unlabelled bullets go to Primary Goals. */
export function parseGoals(body: string): GoalGroup[] {
  const groups: GoalGroup[] = GOAL_SECTIONS.map((s) => ({ ...s, bullets: [] }));
  const by = (k: GoalKey) => groups.find((g) => g.key === k)!;
  let cur: GoalKey = "primary";
  for (const t of toBullets(body)) {
    const m = LABEL.exec(t);
    const k = m ? keyFor(m[1]) : undefined;
    if (m && k) { cur = k; by(k).bullets.push(m[2]); }
    else by(cur).bullets.push(t);
  }
  return groups;
}

/** Backend `goals[].key` for each fixed section (IS-93 contract). */
export const BACKEND_GOAL_KEY: Record<GoalKey, string> = {
  return: "returnRequirements", horizon: "investmentTimeHorizon", primary: "primaryGoals", secondary: "secondaryGoals",
  liquidity: "liquidityNeeds", tax: "taxConsiderations", unique: "uniqueCircumstances",
};
const FROM_BACKEND_KEY = Object.fromEntries(Object.entries(BACKEND_GOAL_KEY).map(([k, v]) => [v, k])) as Record<string, GoalKey>;

/** Groups -> backend `goals` (always 7 entries in order; empty ones kept with `empty:true`). */
export const groupsToBackend = (groups: GoalGroup[]) =>
  GOAL_SECTIONS.map((s) => {
    const bullets = (groups.find((g) => g.key === s.key)?.bullets ?? []).map((b) => b.trim()).filter(Boolean);
    return { key: BACKEND_GOAL_KEY[s.key], title: s.title, bullets, empty: bullets.length === 0, placeholder: "Not yet completed" };
  });

/** Tolerant: backend `goals:[{key,title,bullets}]` -> groups (missing sections are kept empty). */
export function groupsFromBackend(raw: unknown): GoalGroup[] | undefined {
  if (!Array.isArray(raw) || !raw.length) return undefined;
  const groups: GoalGroup[] = GOAL_SECTIONS.map((s) => ({ ...s, bullets: [] }));
  for (const r of raw as { key?: string; title?: string; bullets?: unknown }[]) {
    const k = (r.key && (FROM_BACKEND_KEY[r.key] ?? GOAL_SECTIONS.find((s) => s.key === r.key)?.key)) || (r.title ? keyFor(r.title) : undefined);
    if (k && Array.isArray(r.bullets)) groups.find((g) => g.key === k)!.bullets = r.bullets.map(String).filter((b) => b.trim());
  }
  return groups;
}

/** Sections -> part-1 body, "Heading: bullet" per line (empty sections omitted; shown as "Not yet completed"). */
export const serializeGoals = (groups: GoalGroup[]): string =>
  groups.flatMap((g) => g.bullets.map((b) => b.trim()).filter(Boolean).map((b) => `${g.title}: ${b}`)).join("\n");
