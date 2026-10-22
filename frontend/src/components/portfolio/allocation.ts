import type { PaOption } from "../../types/portfolio";

/** One asset class of a portfolio, with the product sub-classes inside it. */
export interface ClassAlloc {
  assetClass: string;
  pct: number;
  amount: number;
  subs: { name: string; pct: number; amount: number }[];
}

/**
 * The single transform every portfolio view uses: classes exactly as the backend
 * returned them (largest first), each with its sub-classes. No asset-class list is
 * hard-coded, so a new class from the Product Specialist shows up everywhere.
 */
export function allocationOf(o: PaOption): ClassAlloc[] {
  return [...o.asset_allocation]
    .sort((a, b) => b.allocation_percentage - a.allocation_percentage)
    .map((a) => ({
      assetClass: a.asset_class,
      pct: a.allocation_percentage,
      amount: a.investment_amount,
      subs: (o.sub_asset_allocation ?? [])
        .filter((s) => s.asset_class === a.asset_class && s.sub_asset_class !== a.asset_class)
        .map((s) => ({ name: s.sub_asset_class, pct: s.allocation_percentage, amount: s.investment_amount })),
    }));
}

/** Every asset class held by any of `options`, ordered by its largest weight across them. */
export function classUnion(options: PaOption[]): string[] {
  const best = new Map<string, number>();
  options.forEach((o) => o.asset_allocation.forEach((a) => best.set(a.asset_class, Math.max(best.get(a.asset_class) ?? 0, a.allocation_percentage))));
  return [...best.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
}

/** Lux chart tokens, assigned to familiar classes first; any other class takes the next free tone. */
const TONES = ["var(--chart-equities)", "var(--chart-bonds)", "var(--chart-liquidity)", "var(--chart-alternatives)", "var(--scale-fill)", "var(--hairline-strong)", "var(--ink-muted)"];
const PREFERRED: Record<string, number> = { Equities: 0, "Fixed income": 1, Cash: 2, Gold: 3, "Hedge funds": 4, "Private markets": 6, "Real estate": 5 };

export function classColor(assetClass: string): string {
  if (assetClass in PREFERRED) return TONES[PREFERRED[assetClass]];
  let h = 0;
  for (const ch of assetClass) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TONES[h % TONES.length];
}

/** Weights by asset class for one option (what Edit weights starts from). */
export const weightsOf = (o: PaOption): Record<string, number> =>
  Object.fromEntries(o.asset_allocation.map((a) => [a.asset_class, a.allocation_percentage]));
