"""
Contracts for the Product Recommender.

The shelf extends the Portfolio Agent's ProductCandidate with the fields
the PS screen shows; the PM validates the same JSON as ProductCandidate and
ignores the extras. The request reuses the PM's ClientProfile so both agents
see the same client.

Fees appear only in `Costs`, which is marked display-only: nothing in the
ranking reads it.
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.agents.portfolio_agent.schemas.client import _ID_PATTERN, ClientProfile
from app.agents.portfolio_agent.schemas.response import ExplanationStatus
from app.agents.portfolio_agent.schemas.upstream import ProductCandidate, SourceRef

View = Literal["Buy", "Hold", "Sell"]
Confidence = Literal["High", "Medium", "Low"]
ExclusionCode = Literal[
    "DATA_INVALID", "RISK_UNKNOWN", "RISK_ABOVE_LIMIT", "DRAWDOWN", "LIQUIDITY", "LIQUIDITY_NEED",
    "CURRENCY", "RESTRICTED", "SECTOR_EXCLUDED", "ESG", "ELIGIBILITY", "NOT_PREFERRED",
]


# --- Shelf -------------------------------------------------------------------

class ShelfProduct(ProductCandidate):
    why_buy: Optional[str] = None
    suitability_note: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="Product quality rating; a minor tie-breaker only.")


class Shelf(BaseModel):
    model_config = ConfigDict(extra="ignore")
    as_of_date: Optional[date] = None
    base_currency: Optional[str] = None
    products: list[ShelfProduct] = Field(default_factory=list)
    data_sources: list[SourceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    is_illustrative: bool = False


# --- House view --------------------------------------------------------------

class AssetClassHouseView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_class: str
    view: View
    confidence: Confidence
    rationale: str
    citation_id: str
    cio_term: str = Field(description="The CIO's own wording, e.g. 'Attractive'; `view` maps it to Buy/Hold/Sell.")
    basis: Literal["rated", "interpreted", "not_covered"] = Field(
        description="rated: the report states a rating; interpreted: read from the report's prose; "
                    "not_covered: the report gives no view, so Hold/Low is used.")


class HouseView(BaseModel):
    model_config = ConfigDict(extra="ignore")
    as_of: date
    source_document: str
    is_illustrative: bool = False
    views: list[AssetClassHouseView]
    limitations: list[str] = Field(default_factory=list)

    def for_class(self, asset_class: str) -> Optional[AssetClassHouseView]:
        return next((v for v in self.views if v.asset_class == asset_class), None)


# --- Recommend request / response -------------------------------------------

class RecommendOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_n: int = Field(default=5, ge=1, le=20)
    max_per_asset_class: int = Field(default=2, ge=1, le=20)
    asset_classes: Optional[list[str]] = None
    named_products: list[str] = Field(default_factory=list, max_length=20)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    client_id: str = Field(pattern=_ID_PATTERN)
    client_profile: ClientProfile
    options: RecommendOptions = Field(default_factory=RecommendOptions)


class Costs(BaseModel):
    management_fee_pct: Optional[float] = None
    transaction_fee_pct: Optional[float] = None
    display_only: Literal[True] = True


class ScoreBreakdown(BaseModel):
    total: float
    components: dict[str, float]


class ProductSummary(BaseModel):
    product_id: str
    product_name: str
    asset_class: str
    sub_asset_class: Optional[str] = None
    product_type: Optional[str] = None
    risk_rating: Optional[int] = None
    liquidity: Optional[str] = None
    lock_in_period: Optional[str] = None
    currency: str
    currency_hedged: Optional[bool] = None
    why_buy: Optional[str] = None
    suitability_note: Optional[str] = None
    rating: Optional[int] = None


class Reason(BaseModel):
    text: str
    source: Literal["llm", "deterministic"]
    citations: list[str]


class ShortlistItem(BaseModel):
    rank: int
    product: ProductSummary
    score: ScoreBreakdown
    notes: list[str]
    reason: Reason
    costs: Costs


class EligibleItem(BaseModel):
    product_id: str
    product_name: str
    asset_class: str
    total: float


class Exclusion(BaseModel):
    product_id: str
    product_name: str
    asset_class: str
    code: ExclusionCode
    reason: str


class NamedProductResult(BaseModel):
    query: str
    product_id: Optional[str] = None
    status: Literal["shortlisted", "eligible", "excluded", "not_found"]
    reason: str


class ClientSummary(BaseModel):
    risk_level: Optional[int]
    risk_category: Optional[str]
    objective: str
    shortest_horizon_years: Optional[float]
    base_currency: Optional[str]


class RecommendResponse(BaseModel):
    request_id: str
    client_id: str
    generated_at: datetime
    is_illustrative: bool
    sources: dict[str, str]
    client_summary: ClientSummary
    house_view: HouseView
    shortlist: list[ShortlistItem]
    eligible_not_shortlisted: list[EligibleItem]
    excluded: list[Exclusion]
    named_products: list[NamedProductResult]
    missing_information: list[str]
    limitations: list[str]
    explanation_status: Optional[ExplanationStatus] = Field(
        default=None, description="Who wrote the reasons: the LLM (checked by the guardrail) or the rule-based fallback.")
