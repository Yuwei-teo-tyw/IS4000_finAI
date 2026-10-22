"""
Schemas for the two upstream agents' outputs.

Market data follows the Market Researcher's own contract (re-exported
below). The product models are the contract the Product Specialist Agent
API will need to satisfy once the mock is replaced.
They ignore unknown fields (upstream agents may add fields over time) but
every field the Portfolio Agent *uses* is typed, and anything that may
legitimately be unavailable is Optional so it arrives as null rather than
an invented value.
"""
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# The Market Researcher owns its output contract (market_research_output.schema.json,
# generated from this model). It is re-exported here rather than copied, so the
# two agents cannot drift apart.
from app.agents.market_researcher.schemas import MarketResearchOutput  # noqa: F401

SourceType = Literal["MOCK", "LIVE"]


class _Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SourceRef(_Upstream):
    name: str
    source_type: str = Field(description="e.g. MOCK, PRODUCT_DATABASE")
    retrieved_at: Optional[datetime] = None
    url: Optional[str] = None


# --- Product Specialist Agent ------------------------------------------------

class EligibilityRequirements(_Upstream):
    accredited_investor_only: bool = False
    eligible_residencies: Optional[list[str]] = None
    minimum_age: Optional[int] = None


class ProductCandidate(_Upstream):
    product_id: str
    product_name: str
    asset_class: str
    sub_asset_class: Optional[str] = None
    product_type: Optional[str] = None
    issuer: Optional[str] = None
    currency: str
    historical_returns: Optional[dict[str, Optional[float]]] = None
    yield_to_maturity: Optional[float] = None
    distribution_yield: Optional[float] = None
    risk_rating: Optional[int] = Field(default=None, ge=1, le=5)
    volatility: Optional[float] = Field(default=None, ge=0)
    maximum_drawdown: Optional[float] = Field(default=None, le=0, description="Negative %, e.g. -33.9")
    credit_rating: Optional[str] = None
    management_fee: Optional[float] = Field(default=None, ge=0)
    transaction_fee: Optional[float] = Field(default=None, ge=0)
    minimum_investment: Optional[float] = Field(default=None, ge=0)
    liquidity: Optional[Literal["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "AT_MATURITY", "LOCKED"]] = None
    lock_in_period: Optional[str] = None
    duration: Optional[float] = None
    maturity_date: Optional[date] = None
    geographic_exposure: Optional[dict[str, float]] = None
    sector_exposure: Optional[dict[str, float]] = None
    currency_hedged: Optional[bool] = None
    esg_compliant: Optional[bool] = None
    recommended_horizon: Optional[float] = Field(default=None, ge=0, description="Years")
    eligibility_requirements: Optional[EligibilityRequirements] = None
    product_source: Optional[str] = None
    as_of_date: Optional[date] = None
    data_completeness: Optional[Literal["COMPLETE", "PARTIAL", "MINIMAL"]] = None
    is_illustrative: bool = False


class ProductCandidates(_Upstream):
    as_of_date: Optional[date] = None
    base_currency: Optional[str] = None
    products: list[ProductCandidate] = Field(default_factory=list)
    data_sources: list[SourceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    is_illustrative: bool = False


# --- Integration envelope ----------------------------------------------------

class UpstreamResult(BaseModel):
    """What each integration function hands the service.

    `source` is decided by the integration layer (which knows whether it
    called a mock or a live API) - never by the payload's own claims, so a
    mock payload that says "verified" can't promote itself to real data.
    """
    source: SourceType
    status: Literal["OK", "INCOMPLETE", "UNAVAILABLE"]
    data: Optional[Any] = None
    issues: list[str] = Field(default_factory=list)
