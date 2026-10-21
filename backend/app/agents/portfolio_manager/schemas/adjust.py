"""
Contract for re-evaluating an IC's adjusted asset-class weights against a
stored proposal (POST .../portfolio/{request_id}/options/{option_id}/evaluate).
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.agents.portfolio_manager.schemas.response import ConstraintCheck


class WeightEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float] = Field(description="Asset class -> % of the invested portfolio")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassLine(_Out):
    asset_class: str
    original_pct: float
    adjusted_pct: float
    adjusted_amount: float
    change_pp: float
    expected_return_pct: Optional[float] = Field(description="Products in this class, net of fees (assumption)")
    stress_drawdown_pct: Optional[float] = Field(description="Products in this class, worst historical drawdown")
    model_volatility_pct: Optional[float] = Field(description="House assumption for the asset class")


class PortfolioPoint(_Out):
    """Metrics of one set of weights. Model figures place it on the frontier; product
    figures use the selected products' own data (net of fees), like the proposal."""
    model_volatility_pct: Optional[float]
    model_expected_return_pct: Optional[float]
    product_expected_return_pct: Optional[float]
    stress_drawdown_pct: Optional[float]
    growth_asset_share_pct: float
    estimated_annual_fee_pct: Optional[float]
    foreign_currency_exposure_pct: Optional[float]


class FrontierOut(_Out):
    asset_classes: list[str]
    points: list[dict]  # {volatility_pct, expected_return_pct, weights}
    model_label: str
    basis: Literal["ASSUMPTION"] = "ASSUMPTION"
    method: str


class WeightEvaluation(_Out):
    request_id: str
    option_id: str
    option_name: str
    eligible_portfolio_value: float
    lines: list[ClassLine]
    original: PortfolioPoint
    adjusted: PortfolioPoint
    frontier: Optional[FrontierOut]
    frontier_limitation: Optional[str]
    checks: list[ConstraintCheck]
    valid: bool
    notes: list[str]
