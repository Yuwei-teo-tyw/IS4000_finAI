"""
Contract for an asset-class view: the agent's own Buy / Hold / Sell view in
the CIO's format, beside the CIO house view, with the analysis behind it.

Every stance and number here is computed deterministically; any prose that
an LLM adds later must match them (see explain.py guardrails).
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.agents.portfolio_manager.schemas.client import _ID_PATTERN, ClientProfile
from app.agents.product_recommender.schemas import AssetClassHouseView, Confidence, View

SegmentView = Literal["Most preferred", "Neutral", "Least preferred"]
Agreement = Literal["aligned", "differs", "opposed"]

AGENT_LABEL = "Agent view (analysis, not the CIO house view)"


class Ref(BaseModel):
    text: str
    refs: list[str] = Field(default_factory=list)


class SnapshotItem(BaseModel):
    id: str
    name: str
    value: float
    unit: str
    change_1m: Optional[float] = None
    change_3m: Optional[float] = None
    percentile_10y: Optional[float] = None
    observation_date: date
    stale: bool = False
    basis: Literal["level", "change", "relative"]
    reading: float = Field(description="The signal's reading in [-1, 1] before direction and weight.")
    contribution: float = Field(description="direction x reading; positive supports the class.")
    weight: float
    effect: Literal["supports", "weighs", "neutral"]
    why: str


class RegimeRef(BaseModel):
    phase: Optional[str] = None
    confidence: Optional[str] = None
    tilt: Optional[float] = None
    run_id: Optional[str] = None


class Coverage(BaseModel):
    mapped: int
    available: int


class AgentView(BaseModel):
    label: Literal["Agent view (analysis, not the CIO house view)"] = AGENT_LABEL
    view: View
    confidence: Confidence
    score: float = Field(description="Weighted score in [-1, 1]; Buy at or above the Buy cut-off, Sell at or below the Sell cut-off.")
    thesis: str
    thesis_points: list[Ref]
    regime: RegimeRef
    coverage: Coverage
    insufficient_evidence: bool = False


class AgreementResult(BaseModel):
    status: Agreement
    explanation: Optional[str] = None


class SegmentResult(BaseModel):
    group: str
    segment: str
    view: SegmentView
    score: Optional[float] = None
    reason: str
    refs: list[str] = Field(default_factory=list)


class Trigger(BaseModel):
    indicator: str
    condition: str


class Scenario(BaseModel):
    case: Literal["base", "upside", "downside"]
    description: str
    trigger: Optional[Trigger] = None
    stance_implication: str


class ImplementationProduct(BaseModel):
    product_id: str
    product_name: str
    segment: str
    risk_rating: Optional[int] = None
    liquidity: Optional[str] = None
    currency: str
    currency_hedged: Optional[bool] = None


class FeeSummary(BaseModel):
    min_pct: Optional[float] = None
    median_pct: Optional[float] = None
    max_pct: Optional[float] = None
    display_only: Literal[True] = True


class Implementation(BaseModel):
    products: list[ImplementationProduct]
    fees: FeeSummary


class ClientLens(BaseModel):
    client_id: str
    risk_level: Optional[int] = None
    eligible: int
    excluded: dict[str, int] = Field(description="Exclusion code -> number of products in this class.")
    accessible_segments: list[str]
    current_weight_pct: Optional[float] = None


class DataQuality(BaseModel):
    market_source: str
    market_status: str
    market_researcher_run_id: Optional[str] = None
    market_as_of: Optional[date] = None
    market_quality: Optional[str] = None
    stale_indicators: list[str] = Field(default_factory=list)
    missing_indicators: list[str] = Field(default_factory=list)
    house_view_as_of: date


class AssetClassView(BaseModel):
    asset_class: str
    generated_at: datetime
    is_illustrative: bool
    cio_view: AssetClassHouseView
    agent_view: Optional[AgentView] = Field(default=None, description="None when no market data is available.")
    agent_view_unavailable_reason: Optional[str] = None
    agreement: Optional[AgreementResult] = None
    snapshot: list[SnapshotItem]
    segments: list[SegmentResult]
    drivers: list[Ref]
    scenarios: list[Scenario]
    watch_items: list[Ref]
    risks: list[Ref]
    implementation: Implementation
    client_lens: Optional[ClientLens] = None
    narrative_source: Literal["llm", "deterministic"] = "deterministic"
    caveats: list[str]
    data_quality: DataQuality


class AssetClassHeadline(BaseModel):
    asset_class: str
    cio_view: View
    cio_term: str
    cio_confidence: Confidence
    agent_view: Optional[View] = None
    agent_confidence: Optional[Confidence] = None
    agreement: Optional[Agreement] = None


class AssetClassViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(pattern=_ID_PATTERN)
    client_profile: ClientProfile
