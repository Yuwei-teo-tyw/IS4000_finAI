"""
Response schema for POST /portfolio/generate and GET /portfolio/{request_id}.

Provenance is explicit throughout: every rationale statement carries a
`basis` saying whether it is client input, an observed market fact, a
forecast/scenario, a stated assumption, a programmatic calculation, or LLM
interpretation. Numbers come only from the calculation engine; the LLM
narrative is a separate, labelled field that is validated before use.
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Basis = Literal[
    "CLIENT_INPUT",
    "OBSERVED_FACT",
    "FORECAST",
    "SCENARIO",
    "ASSUMPTION",
    "CALCULATION",
    "PRODUCT_DATA",
    "RULE",
    "LLM_INTERPRETATION",
]
SuitabilityStatus = Literal["SUITABLE", "SUITABLE_WITH_MODIFICATIONS", "NOT_SUITABLE", "INFEASIBLE"]
DataStatusValue = Literal["VALIDATED", "INCOMPLETE", "INVALID", "MOCK", "MOCK_INCOMPLETE", "LIVE", "LIVE_INCOMPLETE", "UNAVAILABLE"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Statement(_Out):
    statement: str
    basis: Basis
    source: Optional[str] = None


class DataStatus(_Out):
    client_profile: DataStatusValue
    market_analysis: DataStatusValue
    product_candidates: DataStatusValue


class ClientProfileSummary(_Out):
    base_currency: Optional[str]
    risk_appetite: Optional[str]
    risk_capacity: Optional[str]
    risk_tolerance_score: Optional[int]
    effective_risk_level: Optional[int]
    effective_risk_label: Optional[str]
    effective_risk_basis: Optional[str]
    maximum_acceptable_drawdown: Optional[float]
    primary_goals: list[str]
    shortest_goal_horizon_years: Optional[float]
    review_trigger: Optional[str]


class LiquidityPlan(_Out):
    """How eligible_portfolio_value was derived from investable_assets."""
    investable_assets: Optional[float]
    minimum_cash_reserve_required: Optional[float]
    reserve_already_held_outside_investable_assets: float
    reserve_carved_out: Optional[float]
    near_term_withdrawals_carved_out: Optional[float]
    later_withdrawals_not_carved_out: float
    eligible_portfolio_value: Optional[float]
    notes: list[Statement]


class ScenarioDetail(_Out):
    """A Portfolio Manager stress scenario (house assumption)."""
    name: str
    probability: Optional[float]
    probability_source: Optional[str]
    horizon: Optional[str]
    narrative: str
    asset_class_returns: dict[str, float]
    basis: Basis = "ASSUMPTION"


class RegimeSummary(_Out):
    """The Market Researcher's economic-cycle call, passed through."""
    phase: Optional[str]
    confidence: str
    probabilities: dict[str, float]
    recession_prob_12m: Optional[float]
    in_recession_prob: Optional[float]
    drivers: list[str]
    conflicting_signals: list[str]
    changed: bool


class MarketEvent(_Out):
    id: str
    severity: str
    description: str
    evidence: list[str]


class MarketIndicator(_Out):
    id: str
    name: str
    category: str
    value: float
    unit: str
    observation_date: date
    signal: str
    percentile_10y: Optional[float]
    stale: bool
    source: str
    source_url: str


class MarketNews(_Out):
    title: str
    source: str
    url: str
    published_at: Optional[datetime]
    summary: str
    sentiment: str
    market_impact: str


class MarketContextSummary(_Out):
    """Market Researcher output as used by the Portfolio Manager, plus the
    house assumptions used for expected returns and stress scenarios."""
    data_source_label: str
    run_id: Optional[str]
    as_of: Optional[date]
    region: Optional[str]
    quality_status: Optional[str]
    regime: Optional[RegimeSummary]
    events: list[MarketEvent]
    indicators: list[MarketIndicator]
    market_snapshot: list[MarketIndicator]
    news: list[MarketNews]
    key_themes: list[str]
    risks: list[str]
    implications: dict[str, str]
    key_observations: list[Statement]
    forecasts: list[Statement]
    scenario_details: list[ScenarioDetail]
    assumptions_label: str
    long_term_return_assumptions: dict[str, float]
    limitations: list[str]


class AssetAllocationItem(_Out):
    asset_class: str
    allocation_percentage: float
    investment_amount: float
    change_from_current_pp: Optional[float] = Field(
        default=None, description="Percentage-point change vs current_asset_allocation, where provided"
    )


class ProductSelection(_Out):
    product_id: str
    product_name: str
    asset_class: str
    product_type: Optional[str]
    currency: str
    currency_hedged: Optional[bool]
    allocation_percentage: float
    investment_amount: float
    expected_return_assumption: Optional[float]
    expected_return_basis: Optional[str]
    management_fee: Optional[float]
    estimated_transaction_cost: Optional[float]
    liquidity: Optional[str]
    key_rationale: str
    key_risks: list[str]
    data_provenance: Literal["ILLUSTRATIVE_MOCK", "UPSTREAM_API"]
    as_of_date: Optional[date]
    data_warnings: list[str]
    details: "ProductDetails"


class ProductDetails(_Out):
    """Product Specialist data passed through unchanged (null = not supplied)."""
    sub_asset_class: Optional[str]
    issuer: Optional[str]
    risk_rating: Optional[int]
    historical_returns: Optional[dict[str, Optional[float]]]
    yield_to_maturity: Optional[float]
    distribution_yield: Optional[float]
    volatility: Optional[float]
    maximum_drawdown: Optional[float]
    credit_rating: Optional[str]
    transaction_fee: Optional[float]
    minimum_investment: Optional[float]
    lock_in_period: Optional[str]
    duration: Optional[float]
    maturity_date: Optional[date]
    recommended_horizon: Optional[float]
    geographic_exposure: Optional[dict[str, float]]
    sector_exposure: Optional[dict[str, float]]
    esg_compliant: Optional[bool]
    data_completeness: Optional[str]


class CandidateProduct(_Out):
    """Every product the Product Specialist supplied, with its screening outcome."""
    product_id: str
    product_name: str
    asset_class: str
    product_type: Optional[str]
    currency: str
    currency_hedged: Optional[bool]
    management_fee: Optional[float]
    liquidity: Optional[str]
    screening_status: Literal["SELECTED", "ELIGIBLE_NOT_SELECTED", "EXCLUDED"]
    selected_in_options: list[str]
    exclusion_reason: Optional[str]
    notes: list[str]
    data_provenance: Literal["ILLUSTRATIVE_MOCK", "UPSTREAM_API"]
    as_of_date: Optional[date]
    details: ProductDetails


class PortfolioMetrics(_Out):
    expected_annual_return_pct: Optional[float]
    estimated_volatility_pct: Optional[float]
    estimated_stress_drawdown_pct: Optional[float]
    growth_asset_share_pct: float
    estimated_annual_fee_pct: Optional[float]
    estimated_annual_fee_amount: Optional[float]
    estimated_one_off_transaction_cost: Optional[float]
    high_liquidity_share_pct: Optional[float]
    foreign_currency_exposure_pct: Optional[float]
    number_of_products: int
    number_of_asset_classes: int
    effective_number_of_holdings: Optional[float]
    geographic_exposure_pct: Optional[dict[str, float]] = Field(
        default=None, description="Look-through by allocation weight; null if any holding lacks the data"
    )
    sector_exposure_pct: Optional[dict[str, float]] = Field(
        default=None, description="Look-through by allocation weight; null if any holding lacks the data"
    )
    calculation_notes: list[str]


class ScenarioOutcome(_Out):
    scenario: str
    probability: Optional[float]
    horizon: Optional[str]
    portfolio_return_pct: Optional[float]
    portfolio_value_change: Optional[float]
    basis: Basis = "SCENARIO"


class GoalAlignment(_Out):
    goal: str
    priority: Optional[str]
    target_amount: Optional[float]
    years_to_goal: Optional[float]
    projected_value_base_case: Optional[float]
    status: Literal["ON_TRACK", "SHORTFALL", "NOT_ASSESSABLE"]
    note: str


class ConstraintCheck(_Out):
    constraint: str
    limit: Optional[float]
    actual: Optional[float]
    status: Literal["PASS", "FAIL", "UNVERIFIED", "NOT_APPLICABLE"]
    detail: str


OptionId = Literal["A", "B", "C", "D", "E", "F"]


class PortfolioOption(_Out):
    option_id: OptionId
    option_name: str
    objective: str
    suitability_status: SuitabilityStatus
    suitability_explanation: str
    eligible_portfolio_value: Optional[float]
    base_currency: Optional[str]
    asset_allocation: list[AssetAllocationItem]
    product_selections: list[ProductSelection]
    expected_portfolio_return: Optional[float]
    estimated_risk_level: Optional[str]
    metrics: Optional[PortfolioMetrics]
    scenario_analysis: list[ScenarioOutcome]
    goal_alignment: list[GoalAlignment]
    constraint_checks: list[ConstraintCheck]
    liquidity_assessment: str
    diversification_assessment: str
    advantages: list[str]
    disadvantages: list[str]
    rationale: list[Statement]
    assumptions: list[str]
    warnings: list[str]
    narrative: Optional[str]
    narrative_source: Literal["LLM_INTERPRETATION", "DETERMINISTIC_TEMPLATE", "NONE"]


class ComparisonRow(_Out):
    criterion: str
    values: dict[str, str] = Field(description="Option id -> assessment, for every evaluated option")


class MissingInformation(_Out):
    field: str
    severity: Literal["BLOCKING", "MATERIAL", "MINOR"]
    impact: str


class Conflict(_Out):
    fields: list[str]
    severity: Literal["BLOCKING", "MATERIAL", "INFO"]
    description: str
    resolution: str


class ExcludedProduct(_Out):
    product_id: str
    reason: str


class ExplanationStatus(_Out):
    source: Literal["LLM", "DETERMINISTIC_FALLBACK", "DETERMINISTIC"]
    llm_attempted: bool
    llm_succeeded: bool
    model: Optional[str]
    detail: str


class PortfolioResponse(_Out):
    request_id: str
    client_id: str
    analysis_timestamp: datetime
    status: Literal["COMPLETED", "COMPLETED_WITH_WARNINGS", "INSUFFICIENT_INFORMATION", "CONSTRAINT_CONFLICT"]
    data_status: DataStatus
    client_profile_summary: ClientProfileSummary
    liquidity_plan: Optional[LiquidityPlan]
    market_context_summary: MarketContextSummary
    portfolio_options: list[PortfolioOption]
    comparison_matrix: list[ComparisonRow]
    comparison_summary: Optional[str]
    preferred_option: Optional[OptionId]
    preferred_option_rationale: str
    key_risks: list[str]
    assumptions: list[str]
    missing_information: list[MissingInformation]
    conflicts: list[Conflict]
    excluded_products: list[ExcludedProduct]
    candidate_products: list[CandidateProduct]
    warnings: list[str]
    explanation_status: ExplanationStatus
    requires_rm_review: Literal[True] = True
    execution_status: Literal["NOT_EXECUTED"] = "NOT_EXECUTED"
    disclaimer: str
ProductSelection.model_rebuild()
