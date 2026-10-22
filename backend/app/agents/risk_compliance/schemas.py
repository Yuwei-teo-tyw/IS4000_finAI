"""
Request and report schemas for the Risk & Compliance checks.

Client data reuses the Portfolio Agent's `ClientProfile` (holdings,
goals and withdrawals live there), so the three agents read one profile.
Requests reject unknown fields, like the PM's, so a typo fails loudly.

Every finding names the policy rule it came from (`rule_id`) and the
policy version, and carries an `effect` that decides the report status:

  BLOCK      - cannot go ahead; status BLOCKED
  NEEDS_INFO - missing, stale or unverifiable data; status NEEDS_INFO
  CONDITION  - can go ahead once the RM has seen it; PASS_WITH_CONDITIONS
  NOTE       - recorded only

Percentages are 0-100, amounts in the profile's base_currency.
"""
from datetime import date, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.portfolio_agent.schemas.client import ClientProfile, UpdateTrigger
from app.agents.portfolio_agent.schemas.response import (
    Conflict,
    LiquidityPlan,
    MissingInformation,
)

_ID_PATTERN = r"^[A-Za-z0-9_\-.]{1,64}$"

Status = Literal["PASS", "PASS_WITH_CONDITIONS", "BLOCKED", "NEEDS_INFO"]
Effect = Literal["BLOCK", "NEEDS_INFO", "CONDITION", "NOTE"]
Severity = Literal["BLOCKING", "MATERIAL", "MINOR"]
GateId = Literal["G1", "G2", "G3", "G4"]


def _pct():
    return Field(ge=0, le=100)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ----------------------------------------------------------------

class ConfirmedObjective(_Strict):
    """What the RM confirmed at intake (step 2), recorded with the check."""
    type: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    confirmed_by: Optional[str] = Field(default=None, max_length=100)
    confirmed_at: Optional[datetime] = None


class _ClientRequest(_Strict):
    request_id: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    client_id: str = Field(pattern=_ID_PATTERN)
    client_profile: ClientProfile
    trigger: Optional[UpdateTrigger] = None
    policy_version: Optional[str] = Field(
        default=None, max_length=64,
        description="The policy version the caller expects. A mismatch with the loaded policy blocks the check.",
    )
    reference_date: date

    @model_validator(mode="after")
    def _client_ids_match(self):
        # Same guard as the PM: never pair one client's request with another's profile.
        if self.client_id != self.client_profile.client_id:
            raise ValueError("client_id does not match client_profile.client_id")
        return self


class ReadinessRequest(_ClientRequest):
    objective: Optional[ConfirmedObjective] = None
    profile_as_of: Optional[date] = Field(default=None, description="When the profile was last confirmed. Unknown counts as stale.")


class AllocationRowIn(_Strict):
    """One row of the PM's allocation, as the frontend's AllocationRow."""
    asset_class: str = Field(min_length=1, max_length=100)
    saa: float = _pct()
    current: float = _pct()
    old_taa: float = _pct()
    new_taa: float = _pct()
    band: float = _pct()


class PackProduct(_Strict):
    """One product from the Product Specialist's finalised list."""
    product_id: Optional[str] = Field(default=None, max_length=64)
    product_name: str = Field(min_length=1, max_length=200)
    asset_class: Optional[str] = Field(default=None, max_length=100)
    weight_pct: Optional[float] = Field(default=None, ge=0, le=100)


class PackSectionIn(_Strict):
    n: int = Field(ge=0)
    title: str = Field(max_length=200)
    owner: Literal["rm", "pm", "ps"]
    gate: Optional[GateId] = None
    status: Literal["draft", "ready", "flagged", "approved"]
    text: str = Field(default="", max_length=20000)
    kind: Optional[Literal["signoff"]] = None


class DataAsOf(_Strict):
    """As-of dates of the data the pack was built from. Unknown counts as
    stale. Product dates come from the shelf itself, not from the caller."""
    profile: Optional[date] = None
    market: Optional[date] = None


class ReviewPackCheckRequest(_ClientRequest):
    pack_version: Optional[str] = Field(default=None, max_length=64)
    allocation: list[AllocationRowIn] = Field(default_factory=list)
    products: list[PackProduct] = Field(default_factory=list)
    sections: list[PackSectionIn] = Field(default_factory=list)
    gates: dict[GateId, Literal["not_started", "pending", "approved", "reset"]] = Field(default_factory=dict)
    data_as_of: DataAsOf = Field(default_factory=DataAsOf)


# --- Reports -----------------------------------------------------------------

class RiskFinding(_Out):
    code: str
    severity: Severity
    effect: Effect
    rule_id: str
    policy_version: Optional[str]
    fields: list[str] = Field(default_factory=list)
    observed: Optional[Union[float, str]] = None
    threshold: Optional[Union[float, str]] = None
    message: str


class EffectiveRisk(_Out):
    appetite_level: Optional[int]
    score_level: Optional[int]
    capacity_level: Optional[int]
    effective_level: Optional[int]
    effective_label: Optional[str]
    governed_by: Optional[Literal["capacity", "willingness", "agree"]]
    basis: Optional[str]


class ClientConstraints(_Out):
    """Limits the advice and the final pack must respect, in machine-readable form."""
    effective_risk_level: Optional[int]
    shortest_horizon_years: Optional[float]
    max_growth_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    max_single_product_pct: float
    max_currency_exposure_pct: float
    max_lock_in_months: Optional[float]
    near_term_cash_need_months: Optional[float]
    preferred_asset_classes: Optional[list[str]]
    banned_sectors: list[str]
    restricted_products: list[str]
    esg_required: bool


class _Report(_Out):
    status: Status
    request_id: Optional[str]
    client_id: str
    findings: list[RiskFinding]
    missing_information: list[MissingInformation]
    conflicts: list[Conflict]
    constraints: Optional[ClientConstraints]
    inputs_fingerprint: str
    policy_id: Optional[str]
    policy_version: Optional[str]
    computed_at: datetime


class ReadinessReport(_Report):
    next_step: Literal["ADVISORY", "CLARIFY", "BLOCK"]
    effective_risk: Optional[EffectiveRisk]
    eligible_value: Optional[float]
    liquidity: Optional[LiquidityPlan]
    assumptions: list[str]


class PackCheckReport(_Report):
    pack_version: Optional[str]
    rm_signoff_allowed: bool
