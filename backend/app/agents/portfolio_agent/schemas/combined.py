"""
Contract for the combined 3L review (POST .../portfolio/combined): the
portfolio chosen for each bucket, with any adjusted weights, checked
together against the client's overall position and limits.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.portfolio_agent.schemas.adjust import PortfolioPoint
from app.agents.portfolio_agent.schemas.client import _ID_PATTERN, BucketId
from app.agents.portfolio_agent.schemas.response import ConstraintCheck


class BucketChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: BucketId
    request_id: str = Field(pattern=_ID_PATTERN)
    option_id: Literal["A", "B", "C", "D", "E", "F"]
    weights: Optional[dict[str, float]] = Field(default=None, description="Adjusted class weights; omit for the proposal's")


class CombinedReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_total: Optional[float] = Field(default=None, gt=0, description="Amount the 3L allocation must add up to")
    buckets: list[BucketChoice] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _each_bucket_once(self):
        names = [b.bucket for b in self.buckets]
        if len(set(names)) != len(names):
            raise ValueError("Each bucket may appear only once.")
        ids = [b.request_id for b in self.buckets]
        if len(set(ids)) != len(ids):
            raise ValueError("Each bucket needs its own proposal; the same request_id was given twice.")
        return self


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CombinedBucket(_Out):
    bucket: BucketId
    label: str
    request_id: str
    option_id: str
    option_name: str
    amount: float
    share_pct: float
    point: PortfolioPoint
    checks_pass: bool


class CombinedClass(_Out):
    asset_class: str
    amount: float
    pct: float
    by_bucket: dict[str, float] = Field(description="Bucket -> amount in this asset class")


class CombinedPoint(_Out):
    model_volatility_pct: Optional[float]
    model_expected_return_pct: Optional[float]
    product_expected_return_pct: Optional[float]
    stress_drawdown_pct: Optional[float]
    growth_asset_share_pct: float
    estimated_annual_fee_pct: Optional[float]
    foreign_currency_exposure_pct: float
    fast_dealing_share_pct: float = Field(description="Share in products that deal daily or weekly")
    largest_product: Optional[str]
    largest_product_pct: Optional[float]


class CombinedReview(_Out):
    client_id: str
    total_amount: float
    client_total: Optional[float]
    buckets: list[CombinedBucket]
    classes: list[CombinedClass]
    combined: CombinedPoint
    checks: list[ConstraintCheck]
    valid: bool
    notes: list[str]
    requires_rm_review: Literal[True] = True
    execution_status: Literal["NOT_EXECUTED"] = "NOT_EXECUTED"
