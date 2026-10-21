/**
 * Portfolio Manager agent contract. Mirrors backend/app/agents/portfolio_manager/
 * schemas/{client,response}.py - keep in sync. Pages render the response as-is.
 */

// ---------------------------------------------------------------- Request --

export interface PmGoal { goal: string; target_amount?: number | null; years_to_goal?: number | null; priority?: "High" | "Medium" | "Low" | null; currency?: string | null }

export interface PmClientProfile {
  client_id: string;
  base_currency: string;
  total_aum?: number | null;
  investable_assets?: number | null;
  emergency_fund_included_in_investable_assets?: boolean | null;
  minimum_cash_reserve?: number | null;
  planned_withdrawals?: number | null;
  risk_appetite?: string | null;
  risk_tolerance_score?: number | null;
  risk_capacity?: string | null;
  maximum_acceptable_drawdown?: number | null;
  financial_goals?: PmGoal[] | null;
  current_asset_allocation?: Record<string, number> | null;
}

export interface PmRequest {
  request_id?: string;
  client_id: string;
  trigger?: { life_event?: string | null; requirement_change?: string | null; reason_for_review?: string | null; effective_date?: string | null } | null;
  client_profile: PmClientProfile;
}

/** One input shown to the IC before running the agent: where it came from, or that it is missing. */
export interface PmInputField { label: string; value: string | null; source: string }

export interface PmInputs {
  request: PmRequest;
  fields: PmInputField[];
  /** Notes on how the 3L buckets and IPS were turned into agent inputs. */
  notes: string[];
}

// --------------------------------------------------------------- Response --

export type PmBasis = "CLIENT_INPUT" | "OBSERVED_FACT" | "FORECAST" | "SCENARIO" | "ASSUMPTION" | "CALCULATION" | "PRODUCT_DATA" | "RULE" | "LLM_INTERPRETATION";
export type PmSuitability = "SUITABLE" | "SUITABLE_WITH_MODIFICATIONS" | "NOT_SUITABLE" | "INFEASIBLE";

export interface PmStatement { statement: string; basis: PmBasis; source: string | null }

export interface PmProductDetails {
  sub_asset_class: string | null; issuer: string | null; risk_rating: number | null;
  historical_returns: Record<string, number | null> | null; yield_to_maturity: number | null; distribution_yield: number | null;
  volatility: number | null; maximum_drawdown: number | null; credit_rating: string | null;
  transaction_fee: number | null; minimum_investment: number | null; lock_in_period: string | null;
  duration: number | null; maturity_date: string | null; recommended_horizon: number | null;
  geographic_exposure: Record<string, number> | null; sector_exposure: Record<string, number> | null;
  esg_compliant: boolean | null; data_completeness: string | null;
}

export interface PmProductSelection {
  product_id: string; product_name: string; asset_class: string; product_type: string | null;
  currency: string; currency_hedged: boolean | null; allocation_percentage: number; investment_amount: number;
  expected_return_assumption: number | null; expected_return_basis: string | null;
  management_fee: number | null; estimated_transaction_cost: number | null; liquidity: string | null;
  key_rationale: string; key_risks: string[]; data_provenance: "ILLUSTRATIVE_MOCK" | "UPSTREAM_API";
  as_of_date: string | null; data_warnings: string[]; details: PmProductDetails;
}

export interface PmCandidateProduct {
  product_id: string; product_name: string; asset_class: string; product_type: string | null;
  currency: string; currency_hedged: boolean | null; management_fee: number | null; liquidity: string | null;
  screening_status: "SELECTED" | "ELIGIBLE_NOT_SELECTED" | "EXCLUDED"; selected_in_options: string[];
  exclusion_reason: string | null; notes: string[]; data_provenance: "ILLUSTRATIVE_MOCK" | "UPSTREAM_API";
  as_of_date: string | null; details: PmProductDetails;
}

export interface PmMetrics {
  expected_annual_return_pct: number | null; estimated_volatility_pct: number | null; estimated_stress_drawdown_pct: number | null;
  growth_asset_share_pct: number; estimated_annual_fee_pct: number | null; estimated_annual_fee_amount: number | null;
  estimated_one_off_transaction_cost: number | null; high_liquidity_share_pct: number | null; foreign_currency_exposure_pct: number | null;
  number_of_products: number; number_of_asset_classes: number; effective_number_of_holdings: number | null;
  geographic_exposure_pct: Record<string, number> | null; sector_exposure_pct: Record<string, number> | null;
  calculation_notes: string[];
}

export interface PmScenarioOutcome { scenario: string; probability: number | null; horizon: string | null; portfolio_return_pct: number | null; portfolio_value_change: number | null; basis: PmBasis }
export interface PmGoalAlignment { goal: string; priority: string | null; target_amount: number | null; years_to_goal: number | null; projected_value_base_case: number | null; status: "ON_TRACK" | "SHORTFALL" | "NOT_ASSESSABLE"; note: string }
export interface PmConstraintCheck { constraint: string; limit: number | null; actual: number | null; status: "PASS" | "FAIL" | "UNVERIFIED" | "NOT_APPLICABLE"; detail: string }

export interface PmOption {
  option_id: string; option_name: string; objective: string;
  suitability_status: PmSuitability; suitability_explanation: string;
  eligible_portfolio_value: number | null; base_currency: string | null;
  asset_allocation: { asset_class: string; allocation_percentage: number; investment_amount: number; change_from_current_pp: number | null }[];
  /** By product sub-class (e.g. Government bonds within Fixed income), summed from the products. */
  sub_asset_allocation: { asset_class: string; sub_asset_class: string; allocation_percentage: number; investment_amount: number }[];
  product_selections: PmProductSelection[];
  expected_portfolio_return: number | null; estimated_risk_level: string | null; metrics: PmMetrics | null;
  scenario_analysis: PmScenarioOutcome[]; goal_alignment: PmGoalAlignment[]; constraint_checks: PmConstraintCheck[];
  liquidity_assessment: string; diversification_assessment: string;
  advantages: string[]; disadvantages: string[]; rationale: PmStatement[]; assumptions: string[]; warnings: string[];
  narrative: string | null; narrative_source: "LLM_INTERPRETATION" | "DETERMINISTIC_TEMPLATE" | "NONE";
  /** How this option differs from the next more cautious offered option. */
  key_differences: string[];
}

export interface PmMarketIndicator { id: string; name: string; category: string; value: number; unit: string; observation_date: string; signal: string; percentile_10y: number | null; stale: boolean; source: string; source_url: string }

export interface PmMarketContext {
  data_source_label: string; run_id: string | null; as_of: string | null; region: string | null; quality_status: string | null;
  regime: { phase: string | null; confidence: string; probabilities: Record<string, number>; recession_prob_12m: number | null; in_recession_prob: number | null; drivers: string[]; conflicting_signals: string[]; changed: boolean } | null;
  events: { id: string; severity: string; description: string; evidence: string[] }[];
  indicators: PmMarketIndicator[]; market_snapshot: PmMarketIndicator[];
  news: { title: string; source: string; url: string; published_at: string | null; summary: string; sentiment: string; market_impact: string }[];
  key_themes: string[]; risks: string[]; implications: Record<string, string>;
  key_observations: PmStatement[]; forecasts: PmStatement[];
  scenario_details: { name: string; probability: number | null; probability_source: string | null; horizon: string | null; narrative: string; asset_class_returns: Record<string, number>; basis: PmBasis }[];
  assumptions_label: string; long_term_return_assumptions: Record<string, number>; limitations: string[];
}

export interface PmLiquidityPlan {
  investable_assets: number | null; minimum_cash_reserve_required: number | null; reserve_already_held_outside_investable_assets: number;
  reserve_carved_out: number | null; near_term_withdrawals_carved_out: number | null; later_withdrawals_not_carved_out: number;
  eligible_portfolio_value: number | null; notes: PmStatement[];
}

export interface PmResponse {
  request_id: string; client_id: string; analysis_timestamp: string;
  status: "COMPLETED" | "COMPLETED_WITH_WARNINGS" | "INSUFFICIENT_INFORMATION" | "CONSTRAINT_CONFLICT";
  data_status: { client_profile: string; market_analysis: string; product_candidates: string };
  client_profile_summary: { effective_risk_level: number | null; effective_risk_label: string | null; effective_risk_basis: string | null; shortest_goal_horizon_years: number | null; maximum_acceptable_drawdown: number | null; base_currency: string | null };
  liquidity_plan: PmLiquidityPlan | null;
  market_context_summary: PmMarketContext;
  portfolio_options: PmOption[];
  comparison_matrix: { criterion: string; values: Record<string, string> }[];
  comparison_summary: string | null;
  preferred_option: string | null; preferred_option_rationale: string;
  key_risks: string[]; assumptions: string[];
  missing_information: { field: string; severity: "BLOCKING" | "MATERIAL" | "MINOR"; impact: string }[];
  conflicts: { fields: string[]; severity: "BLOCKING" | "MATERIAL" | "INFO"; description: string; resolution: string }[];
  excluded_products: { product_id: string; reason: string }[];
  candidate_products: PmCandidateProduct[];
  warnings: string[];
  explanation_status: { source: "LLM" | "DETERMINISTIC_FALLBACK" | "DETERMINISTIC"; llm_attempted: boolean; llm_succeeded: boolean; model: string | null; detail: string };
  requires_rm_review: true; execution_status: "NOT_EXECUTED"; disclaimer: string;
}

// ------------------------------------------------- Adjusted weights (Edit weights) --

export interface PmPortfolioPoint {
  model_volatility_pct: number | null; model_expected_return_pct: number | null; product_expected_return_pct: number | null;
  stress_drawdown_pct: number | null; growth_asset_share_pct: number; estimated_annual_fee_pct: number | null; foreign_currency_exposure_pct: number | null;
}

export interface PmFrontier {
  asset_classes: string[];
  points: { volatility_pct: number; expected_return_pct: number; weights: Record<string, number> }[];
  model_label: string; basis: "ASSUMPTION"; method: string;
}

export interface PmWeightEvaluation {
  request_id: string; option_id: string; option_name: string; eligible_portfolio_value: number;
  lines: { asset_class: string; original_pct: number; adjusted_pct: number; adjusted_amount: number; change_pp: number;
    expected_return_pct: number | null; stress_drawdown_pct: number | null; model_volatility_pct: number | null }[];
  original: PmPortfolioPoint; adjusted: PmPortfolioPoint;
  frontier: PmFrontier | null; frontier_limitation: string | null;
  checks: PmConstraintCheck[]; valid: boolean; notes: string[];
}

export const OFFERED: PmSuitability[] = ["SUITABLE", "SUITABLE_WITH_MODIFICATIONS"];
export const isOffered = (o: PmOption) => OFFERED.includes(o.suitability_status);

/** POST /portfolio/{request_id}/ask: one chat answer grounded in a stored proposal. */
export interface PmChatTurn { question: string; answer: string }
export interface PmAnswer {
  request_id: string;
  answer: string;
  source: "LLM" | "DETERMINISTIC_FALLBACK" | "DETERMINISTIC";
  model: string | null;
  detail: string;
  options_referenced: string[];
  requires_rm_review: true;
  execution_status: "NOT_EXECUTED";
}
/** What the chat shows: the answer plus which proposal it came from. */
export interface PmChatReply extends PmAnswer {
  /** "ic" = the proposal the IC is working on in the SAA request; "chat" = a run made just for this chat. */
  basis: "ic" | "chat";
}
