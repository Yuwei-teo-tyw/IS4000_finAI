"""Contracts for the model SAA recommendation (GET .../clients/{id}/saa-recommendation) and weight check."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["OK", "INCOMPLETE", "UNAVAILABLE"]
CheckStatus = Literal["PASS", "WARN", "FAIL"]


class ClientFact(BaseModel):
    label: str
    value: str
    source: str


class ThreeLBucket(BaseModel):
    pct: Optional[float] = None
    amount: Optional[float] = None


class HoldingsView(BaseModel):
    available: bool
    message: Optional[str] = None
    # bucket -> {"value": float, "classes": {holding asset class: % of the bucket}}
    by_bucket: dict[str, dict] = Field(default_factory=dict)
    source: str = "Client Portfolio Agent"


class ClientContext(BaseModel):
    client_id: str
    client_name: str
    ips_version: Optional[int] = None
    ips_status: Optional[str] = None
    ips_basis: str
    has_ips_data: bool = False
    total_wealth: Optional[float] = None
    three_l: dict[str, ThreeLBucket]
    three_l_source: str
    risk_level: Optional[int] = None
    risk_level_basis: Optional[str] = None
    risk_score: Optional[int] = None
    product_risk_limit: Optional[int] = None
    risk_tolerance: Optional[str] = None
    risk_capacity: Optional[str] = None
    loss_tolerance_pct: Optional[float] = None
    horizon_text: Optional[str] = None
    horizon_years: Optional[float] = None
    liquidity_needs: Optional[str] = None
    goals: list[str] = Field(default_factory=list)
    targets: list[dict] = Field(default_factory=list)
    approach: Optional[str] = None
    believes: Optional[str] = None
    restrictions: Optional[str] = None
    excluded_asset_classes: list[str] = Field(default_factory=list)
    asset_class_caps: dict[str, float] = Field(default_factory=dict)  # stated by the client, e.g. {"Equities": 10}
    age: Optional[int] = None
    holdings: HoldingsView
    facts: list[ClientFact] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class MarketInfo(BaseModel):
    status: Status
    source: str = "Market Analysis Agent"
    run_id: Optional[str] = None
    region: Optional[str] = None
    generated_at: Optional[str] = None
    as_of: Optional[str] = None
    retrieved_at: str
    regime_phase: Optional[str] = None
    regime_confidence: Optional[str] = None
    key_themes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    implications: dict[str, str] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class ProductItem(BaseModel):
    product_id: str
    product_name: str
    asset_class: str
    sub_asset_class: Optional[str] = None
    product_type: Optional[str] = None
    currency: Optional[str] = None
    risk_rating: Optional[int] = None
    return_1y_pct: Optional[float] = None
    return_3y_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    management_fee_pct: Optional[float] = None
    liquidity: Optional[str] = None
    lock_in: Optional[str] = None
    note: Optional[str] = None


class ProductsView(BaseModel):
    status: Status
    source: str = "Product Specialist Agent"
    shelf_source: Optional[str] = None
    as_of: Optional[str] = None
    by_asset_class: dict[str, list[ProductItem]] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CriterionScore(BaseModel):
    criterion: str
    label: str
    score: float
    max: float
    detail: str


class Metrics(BaseModel):
    growth_share_pct: float
    illiquid_share_pct: float
    long_term_return_pct: Optional[float] = None
    recession_return_pct: Optional[float] = None
    assumptions_label: Optional[str] = None


class ModelEvaluation(BaseModel):
    model_id: str
    model_name: str
    risk_level: int
    strategy_code: str
    purpose: str
    rationale: str
    objectives: list[str]
    min_horizon_years: float
    weights: dict[str, float]
    suitable: bool
    unsuitable_reasons: list[str] = Field(default_factory=list)
    score: Optional[float] = None
    rank: Optional[int] = None
    criteria: list[CriterionScore] = Field(default_factory=list)
    metrics: Metrics


class Alternative(BaseModel):
    model_id: str
    model_name: str
    score: float
    why_not: list[str]


class Recommendation(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    decided_by: Literal["llm", "rules"] = "rules"  # llm: the Portfolio Agent's LLM chose among the suitable models
    llm_model: Optional[str] = None
    llm_note: Optional[str] = None  # why the rule-based pick is shown (LLM off, failed or rejected by guardrails)
    model_id: str
    model_name: str
    strategy_code: str
    score: float
    model_weights: dict[str, float]
    recommended_weights: dict[str, float]
    weight_adjustments: list[str] = Field(default_factory=list)
    summary: str
    reasons: list[str]
    client_factors: list[str]
    market_considerations: list[str]
    risks: list[str]
    existing_holdings: list[str]
    alternatives: list[Alternative] = Field(default_factory=list)


class SaaRecommendationResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    request_id: str
    client_id: str
    bucket: Literal["longevity", "legacy"]
    bucket_label: str
    bucket_purpose: str
    generated_at: str
    library_version: str
    methodology: str
    bucket_amount: Optional[float] = None
    bucket_pct: Optional[float] = None
    horizon_years: Optional[float] = None
    horizon_basis: str
    objectives: list[str]
    objectives_basis: str
    client: ClientContext
    market: MarketInfo
    products: ProductsView
    evaluations: list[ModelEvaluation]
    recommendation: Optional[Recommendation] = None
    no_recommendation_reason: Optional[str] = None
    data_status: dict[str, str]


class WeightCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    bucket: Literal["longevity", "legacy"]
    model_id: str = Field(min_length=1, max_length=20)
    weights: dict[str, float] = Field(max_length=20)


class WeightCheck(BaseModel):
    id: str
    label: str
    status: CheckStatus
    detail: str


class WeightCheckResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    client_id: str
    bucket: str
    model_id: str
    valid: bool
    total_pct: float
    checks: list[WeightCheck]
    metrics: Metrics
    amounts: dict[str, Optional[float]]
