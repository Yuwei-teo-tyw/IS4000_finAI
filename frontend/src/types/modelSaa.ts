/** Portfolio Agent model SAA recommendation (backend model_saa/schemas.py). Read-only; the PM approves. */
export type SaaBucketId = "longevity" | "legacy";
export type AgentStatus = "OK" | "INCOMPLETE" | "UNAVAILABLE";

export interface ClientFact { label: string; value: string; source: string }
export interface ModelSaaContext {
  client_id: string; client_name: string; ips_version: number | null; ips_status: string | null; ips_basis: string;
  total_wealth: number | null; three_l: Record<string, { pct: number | null; amount: number | null }>; three_l_source: string;
  risk_level: number | null; risk_level_basis: string | null; loss_tolerance_pct: number | null; horizon_years: number | null;
  restrictions: string | null; excluded_asset_classes: string[];
  holdings: { available: boolean; message: string | null; by_bucket: Record<string, { value: number; classes: Record<string, number> }>; source: string };
  facts: ClientFact[]; missing: string[];
}
export interface MarketInfo {
  status: AgentStatus; source: string; run_id: string | null; region: string | null; generated_at: string | null; as_of: string | null;
  retrieved_at: string; regime_phase: string | null; regime_confidence: string | null; key_themes: string[]; risks: string[];
  implications: Record<string, string>; issues: string[];
}
export interface ProductItem {
  product_id: string; product_name: string; asset_class: string; sub_asset_class: string | null; product_type: string | null; currency: string | null;
  risk_rating: number | null; return_1y_pct: number | null; return_3y_pct: number | null; max_drawdown_pct: number | null;
  management_fee_pct: number | null; liquidity: string | null; lock_in: string | null; note: string | null;
}
export interface ProductsView {
  status: AgentStatus; source: string; shelf_source: string | null; as_of: string | null;
  by_asset_class: Record<string, ProductItem[]>; gaps: string[]; issues: string[]; limitations: string[];
}
export interface CriterionScore { criterion: string; label: string; score: number; max: number; detail: string }
export interface SaaMetrics { growth_share_pct: number; illiquid_share_pct: number; long_term_return_pct: number | null; recession_return_pct: number | null; assumptions_label: string | null }
export interface ModelEvaluation {
  model_id: string; model_name: string; risk_level: number; strategy_code: string; purpose: string; rationale: string; objectives: string[];
  min_horizon_years: number; weights: Record<string, number>; suitable: boolean; unsuitable_reasons: string[]; score: number | null; rank: number | null;
  criteria: CriterionScore[]; metrics: SaaMetrics;
}
export interface SaaRecommendation {
  /** llm: the Portfolio Agent's LLM chose among the suitable models; rules: the scoring framework did (llm_note says why). */
  decided_by: "llm" | "rules"; llm_model: string | null; llm_note: string | null;
  model_id: string; model_name: string; strategy_code: string; score: number; model_weights: Record<string, number>; recommended_weights: Record<string, number>;
  weight_adjustments: string[]; summary: string; reasons: string[]; client_factors: string[]; market_considerations: string[]; risks: string[];
  existing_holdings: string[]; alternatives: { model_id: string; model_name: string; score: number; why_not: string[] }[];
}
export interface SaaRecommendationResponse {
  request_id: string; client_id: string; bucket: SaaBucketId; bucket_label: string; bucket_purpose: string; generated_at: string; library_version: string;
  methodology: string; bucket_amount: number | null; bucket_pct: number | null; horizon_years: number | null; horizon_basis: string;
  objectives: string[]; objectives_basis: string; client: ModelSaaContext; market: MarketInfo; products: ProductsView;
  evaluations: ModelEvaluation[]; recommendation: SaaRecommendation | null; no_recommendation_reason: string | null; data_status: Record<string, string>;
}
export interface SaaCheck { id: string; label: string; status: "PASS" | "WARN" | "FAIL"; detail: string }
export interface SaaCheckResponse { client_id: string; bucket: string; model_id: string; valid: boolean; total_pct: number; checks: SaaCheck[]; metrics: SaaMetrics; amounts: Record<string, number | null> }

/** The PM's working SAA for one bucket: the model, what the agent recommended, and the PM's amended weights. */
export interface PmModelSaa {
  modelId: string; modelName: string; strategy: string; modelWeights: Record<string, number>;
  recommendedModelId: string | null; recommendedWeights: Record<string, number> | null; recommendationId: string | null;
  weights: Record<string, number>; overrideReason: string;
}
