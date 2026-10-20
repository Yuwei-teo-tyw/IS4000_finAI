/**
 * Product Recommender agent contract. Mirrors backend/app/agents/product_recommender/
 * schemas.py - keep in sync. Fees (`costs`) are display-only and never ranked.
 */
import type { PmClientProfile } from "./portfolio";

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
export interface PrRequest { request_id?: string; client_id: string; client_profile: PmClientProfile; options?: PrOptions }

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
}
