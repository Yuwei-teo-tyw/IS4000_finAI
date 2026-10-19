import type { PmBasis, PmProductDetails } from "../../types/portfolio";

/** Missing values render as a dash, never as 0, so "not supplied" can't read as "zero". */
export const DASH = "—";

export const pct = (v: number | null | undefined, digits = 1, signed = false) =>
  v === null || v === undefined || Number.isNaN(v) ? DASH : `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const sgdAmt = (v: number | null | undefined) =>
  v === null || v === undefined ? DASH : `S$${Math.round(v).toLocaleString("en-SG")}`;

export const years = (v: number | null | undefined) => (v === null || v === undefined ? DASH : `${v} yrs`);

export const LIQUIDITY: Record<string, string> = {
  DAILY: "Daily", WEEKLY: "Weekly", MONTHLY: "Monthly", QUARTERLY: "Quarterly", AT_MATURITY: "At maturity", LOCKED: "Locked",
};

export const BASIS_LABEL: Record<PmBasis, string> = {
  CLIENT_INPUT: "Client input", OBSERVED_FACT: "Observed", FORECAST: "Forecast", SCENARIO: "Scenario",
  ASSUMPTION: "Assumption", CALCULATION: "Calculation", PRODUCT_DATA: "Product data", RULE: "Rule", LLM_INTERPRETATION: "AI interpretation",
};

export const STATUS_LABEL: Record<string, string> = {
  SUITABLE: "Suitable", SUITABLE_WITH_MODIFICATIONS: "Suitable, adapted", NOT_SUITABLE: "Not offered", INFEASIBLE: "Infeasible",
};

export const PHASE_LABEL: Record<string, string> = {
  early_expansion: "Early expansion", late_expansion: "Late expansion", recession: "Recession", late_recession: "Late recession",
};

export function historical(d: PmProductDetails): string {
  const parts = Object.entries(d.historical_returns ?? {}).filter(([, v]) => v !== null).map(([k, v]) => `${k} ${pct(v)}`);
  return parts.length ? parts.join(" · ") : DASH;
}

export function currentYield(d: PmProductDetails): string {
  if (d.yield_to_maturity !== null) return `${pct(d.yield_to_maturity, 2)} YTM`;
  if (d.distribution_yield !== null) return `${pct(d.distribution_yield, 2)} distribution`;
  return DASH;
}

export function fx(currency: string, hedged: boolean | null): string {
  if (currency === "SGD") return "SGD";
  return hedged ? `${currency}, hedged to SGD` : `${currency}, unhedged`;
}
