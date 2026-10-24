"""
Request schema for POST /portfolio/generate.

Most client-profile fields are Optional on purpose: an incomplete profile
is a normal business case (the RM hasn't captured something yet) and must
produce a structured "missing information" response, not a bare 422.
Pydantic here only enforces *types and ranges*; completeness and
consistency are judged in engine/profile_assessment.py, where they can be
reported field-by-field.

Percentages are expressed as 0-100 (15 means 15%), amounts in the
profile's base_currency.
"""
from datetime import date
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_PATTERN = r"^[A-Za-z0-9_\-.]{1,64}$"


def _non_negative():
    return Field(default=None, ge=0)


def _percent():
    return Field(default=None, ge=0, le=100)


class _Strict(BaseModel):
    # Reject unknown fields so a typo ("risk_apetite") fails loudly instead
    # of silently dropping information the RM thought they had provided.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UpdateTrigger(_Strict):
    life_event: Optional[str] = Field(default=None, max_length=500)
    requirement_change: Optional[str] = Field(default=None, max_length=500)
    reason_for_review: Optional[str] = Field(default=None, max_length=1000)
    effective_date: Optional[date] = None


class FinancialGoal(_Strict):
    goal: str = Field(min_length=1, max_length=200, description="Goal description")
    target_amount: Optional[float] = _non_negative()
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    years_to_goal: Optional[float] = Field(default=None, gt=0, le=100)
    target_date: Optional[date] = None
    priority: Optional[Literal["High", "Medium", "Low"]] = None
    horizon: Optional[Literal["Short", "Medium", "Long"]] = None

    @field_validator("priority", mode="before")
    @classmethod
    def _title_case_priority(cls, v):
        return v.strip().title() if isinstance(v, str) else v

    @field_validator("currency", mode="before")
    @classmethod
    def _upper_currency(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class Holding(_Strict):
    product_id: Optional[str] = Field(default=None, max_length=64)
    product_name: Optional[str] = Field(default=None, max_length=200)
    asset_class: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    market_value: float = Field(ge=0)
    unrealised_gain_loss: Optional[float] = None


class PlannedWithdrawal(_Strict):
    amount: float = Field(gt=0)
    expected_date: Optional[date] = None
    months_from_now: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, max_length=200)


class EsgPreferences(_Strict):
    level: Literal["None", "Preferred", "Required"] = "None"
    notes: Optional[str] = Field(default=None, max_length=500)


class ClientProfile(_Strict):
    # Basic information
    client_id: str = Field(pattern=_ID_PATTERN)
    age: Optional[int] = Field(default=None, ge=18, le=120)
    residency: Optional[str] = Field(default=None, max_length=100)
    base_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    accredited_investor: Optional[bool] = None

    # Financial position
    total_aum: Optional[float] = _non_negative()
    investable_assets: Optional[float] = _non_negative()
    annual_income: Optional[float] = _non_negative()
    monthly_expenses: Optional[float] = _non_negative()
    liabilities: Optional[float] = _non_negative()
    emergency_fund: Optional[float] = _non_negative()
    emergency_fund_included_in_investable_assets: Optional[bool] = Field(
        default=None,
        description=(
            "Whether `emergency_fund` is part of `investable_assets`. Unknown -> the reserve is "
            "conservatively carved out of investable assets and the assumption is flagged."
        ),
    )
    cash_balance: Optional[float] = _non_negative()

    # Existing portfolio
    current_holdings: Optional[list[Holding]] = None
    current_asset_allocation: Optional[dict[str, float]] = None
    unrealised_gains_losses: Optional[float] = None

    # Risk profile
    risk_appetite: Optional[str] = Field(default=None, max_length=50)
    risk_tolerance_score: Optional[int] = Field(default=None, ge=1, le=5)
    risk_capacity: Optional[str] = Field(default=None, max_length=50)
    maximum_acceptable_drawdown: Optional[float] = Field(default=None, gt=0, le=100)

    # Investment goals
    financial_goals: Optional[list[FinancialGoal]] = None
    target_amount: Optional[float] = _non_negative()
    target_date: Optional[date] = None
    short_term_goals: Optional[list[str]] = None
    medium_term_goals: Optional[list[str]] = None
    long_term_goals: Optional[list[str]] = None

    # Liquidity needs
    planned_withdrawals: Optional[Union[float, list[PlannedWithdrawal]]] = None
    minimum_cash_reserve: Optional[float] = _non_negative()

    # Preferences
    preferred_asset_classes: Optional[list[str]] = None
    excluded_sectors: Optional[list[str]] = None
    esg_preferences: Optional[EsgPreferences] = None
    restricted_products: Optional[list[str]] = None

    # Investment constraints
    maximum_single_asset_allocation: Optional[float] = Field(default=None, gt=0, le=100)
    maximum_currency_exposure: Optional[float] = _percent()

    @field_validator("base_currency", mode="before")
    @classmethod
    def _upper_currency(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("planned_withdrawals", mode="before")
    @classmethod
    def _non_negative_withdrawal(cls, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            raise ValueError("planned_withdrawals cannot be negative")
        return v

    @field_validator("current_asset_allocation")
    @classmethod
    def _allocation_ranges(cls, v):
        if v is not None:
            for k, pct in v.items():
                if pct < 0 or pct > 100:
                    raise ValueError(f"current_asset_allocation[{k!r}] must be between 0 and 100")
        return v


BucketId = Literal["liquidity", "longevity", "legacy"]


class BucketContext(_Strict):
    """One 3L bucket to build an SAA for. The client profile still describes the whole client
    (risk capacity, limits, liabilities); only `amount` is invested, for this bucket's purpose."""
    bucket: BucketId
    amount: float = Field(gt=0, description="Amount assigned to this bucket in the 3L allocation")
    horizon_years: Optional[float] = Field(
        default=None, gt=0, le=100,
        description="Investment horizon for this bucket, set by the PM; else the bucket's goals decide it",
    )
    objective: Optional[str] = Field(default=None, max_length=300, description="What this bucket is for")
    risk_tolerance_score: Optional[int] = Field(
        default=None, ge=1, le=5,
        description="Risk willingness for this bucket's objective, if it differs from the client's overall "
                    "appetite. Risk capacity still caps it.",
    )
    total_3l_amount: Optional[float] = Field(default=None, gt=0, description="All three buckets together")


class PortfolioGenerateRequest(_Strict):
    request_id: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    client_id: str = Field(pattern=_ID_PATTERN)
    trigger: Optional[UpdateTrigger] = None
    client_profile: ClientProfile
    bucket: Optional[BucketContext] = Field(
        default=None, description="Build the SAA for one 3L bucket instead of the whole portfolio",
    )

    @model_validator(mode="after")
    def _client_ids_match(self):
        # A mismatch means the request may be pairing one client's trigger
        # with another client's profile - refuse rather than guess which is right.
        if self.client_id != self.client_profile.client_id:
            raise ValueError("client_id does not match client_profile.client_id")
        return self
