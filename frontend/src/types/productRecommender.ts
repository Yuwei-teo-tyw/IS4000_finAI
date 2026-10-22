/**
 * Product Recommender agent contract. Mirrors backend/app/agents/product_recommender/
 * schemas.py - keep in sync. Fees (`costs`) are display-only and never ranked.
 */
import type { PaClientProfile } from "./portfolio";

export type PrView = "Buy" | "Hold" | "Sell";
export type PrConfidence = "High" | "Medium" | "Low";

export interface PrShelfProduct {
  product_id: string; product_name: string; asset_class: string; sub_asset_class: string | null; product_type: string | null;
  currency: string; currency_hedged: boolean | null; risk_rating: number | null; liquidity: string | null; lock_in_period: string | null;
  management_fee: number | null; transaction_fee: number | null; distribution_yield: number | null; recommended_horizon: number | null;
  why_buy: string | null; suitability_note: string | null; rating: number | null; is_illustrative: boolean;
}
export interface PrShelf { source: string; status: string; issues: string[]; fees_display_only: true; as_of_date: string | null; is_illustrative: boolean; limitations: string[]; products: PrShelfProduct[] }

export interface PrAssetClassView {
  asset_class: string; view: PrView; confidence: PrConfidence; rationale: string; citation_id: string;
  cio_term: string; basis: "rated" | "interpreted" | "not_covered";
}
export interface PrHouseView { as_of: string; source_document: string; is_illustrative: boolean; views: PrAssetClassView[]; limitations: string[] }

export interface PrOptions { top_n?: number; max_per_asset_class?: number; asset_classes?: string[] | null; named_products?: string[] }
export interface PrRequest { request_id?: string; client_id: string; client_profile: PaClientProfile; options?: PrOptions }

export interface PrProductSummary {
  product_id: string; product_name: string; asset_class: string; sub_asset_class: string | null; product_type: string | null;
  risk_rating: number | null; liquidity: string | null; lock_in_period: string | null; currency: string; currency_hedged: boolean | null;
  why_buy: string | null; suitability_note: string | null; rating: number | null;
}
export interface PrShortlistItem {
  rank: number; product: PrProductSummary; score: { total: number; components: Record<string, number> }; notes: string[];
  reason: { text: string; source: "llm" | "deterministic"; citations: string[] };
  costs: { management_fee_pct: number | null; transaction_fee_pct: number | null; display_only: true };
}
export type PrExclusionCode =
  | "DATA_INVALID" | "RISK_UNKNOWN" | "RISK_ABOVE_LIMIT" | "DRAWDOWN" | "LIQUIDITY" | "LIQUIDITY_NEED"
  | "CURRENCY" | "RESTRICTED" | "SECTOR_EXCLUDED" | "ESG" | "ELIGIBILITY" | "NOT_PREFERRED";
export interface PrExclusion { product_id: string; product_name: string; asset_class: string; code: PrExclusionCode; reason: string }
export interface PrNamedProduct { query: string; product_id: string | null; status: "shortlisted" | "eligible" | "excluded" | "not_found"; reason: string }

/** Who wrote the text: the LLM (from engine facts, checked by the guardrail) or the rule-based fallback. */
export interface PrExplanationStatus {
  source: "LLM" | "DETERMINISTIC_FALLBACK" | "DETERMINISTIC"; llm_attempted: boolean; llm_succeeded: boolean; model: string | null; detail: string;
}
export interface PrResponse {
  request_id: string; client_id: string; generated_at: string; is_illustrative: boolean; sources: Record<string, string>;
  client_summary: { risk_level: number | null; risk_category: string | null; objective: string; shortest_horizon_years: number | null; base_currency: string | null };
  house_view: PrHouseView;
  shortlist: PrShortlistItem[];
  eligible_not_shortlisted: { product_id: string; product_name: string; asset_class: string; total: number }[];
  excluded: PrExclusion[];
  named_products: PrNamedProduct[];
  missing_information: string[];
  limitations: string[];
  explanation_status: PrExplanationStatus | null;
}

/* ---- Asset-class views: the agent's own view beside the CIO's (asset_views/schemas.py) ---- */
export type PrSegmentView = "Most preferred" | "Neutral" | "Least preferred";
export type PrAgreement = "aligned" | "differs" | "opposed";
export interface PrRef { text: string; refs: string[] }
export interface PrSnapshotItem {
  id: string; name: string; value: number; unit: string; change_1m: number | null; change_3m: number | null; percentile_10y: number | null;
  observation_date: string; stale: boolean; basis: "level" | "change" | "relative"; reading: number; contribution: number; weight: number;
  effect: "supports" | "weighs" | "neutral"; why: string;
}
export interface PrAgentView {
  label: string; view: PrView; confidence: PrConfidence; score: number; thesis: string; thesis_points: PrRef[];
  regime: { phase: string | null; confidence: string | null; tilt: number | null; run_id: string | null };
  coverage: { mapped: number; available: number }; insufficient_evidence: boolean;
}
export interface PrSegment { group: string; segment: string; view: PrSegmentView; score: number | null; reason: string; refs: string[] }
export interface PrScenario { case: "base" | "upside" | "downside"; description: string; trigger: { indicator: string; condition: string } | null; stance_implication: string }
export interface PrImplementationProduct {
  product_id: string; product_name: string; segment: string; risk_rating: number | null; liquidity: string | null; currency: string; currency_hedged: boolean | null;
}
export interface PrClientLens {
  client_id: string; risk_level: number | null; eligible: number; excluded: Record<string, number>; accessible_segments: string[]; current_weight_pct: number | null;
}
/** One asset class: the CIO house view entry (`cio_view`, reported verbatim) and the agent's own analysis beside it. */
export interface PrAssetView {
  asset_class: string; generated_at: string; is_illustrative: boolean;
  cio_view: PrAssetClassView;
  agent_view: PrAgentView | null; agent_view_unavailable_reason: string | null;
  agreement: { status: PrAgreement; explanation: string | null } | null;
  snapshot: PrSnapshotItem[]; segments: PrSegment[]; drivers: PrRef[]; scenarios: PrScenario[]; watch_items: PrRef[]; risks: PrRef[];
  implementation: { products: PrImplementationProduct[]; fees: { min_pct: number | null; median_pct: number | null; max_pct: number | null; display_only: true } };
  client_lens: PrClientLens | null;
  narrative_source: "llm" | "deterministic";
  explanation_status: PrExplanationStatus | null;
  caveats: string[];
  data_quality: {
    market_source: string; market_status: string; market_researcher_run_id: string | null; market_as_of: string | null; market_quality: string | null;
    stale_indicators: string[]; missing_indicators: string[]; house_view_as_of: string;
  };
}
export interface PrAssetClassHeadline {
  asset_class: string; cio_view: PrView; cio_term: string; cio_confidence: PrConfidence;
  agent_view: PrView | null; agent_confidence: PrConfidence | null; agreement: PrAgreement | null;
}
