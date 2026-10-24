"""
The versioned risk & compliance policy (data/policy.json): thresholds for
the new checks and the effect of every rule.

The values are placeholders until the policy owner signs them off (see the
file's `_notice`). Rules reused from the Portfolio Agent and Product
Recommender keep their own constants; this file only governs the checks
this agent adds. A missing, malformed or incomplete policy is refused, and
the service then blocks every check rather than running without one.
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.risk_compliance.schemas import Effect, RiskFinding, Severity

logger = logging.getLogger(__name__)

POLICY_PATH = Path(__file__).parent / "data" / "policy.json"

# Every rule the checks can raise. A policy that leaves one out is refused,
# so no finding is ever produced without a policy-defined effect.
RULE_IDS = (
    "READY.REQUIRED_FIELD", "READY.HORIZON_VS_RISK",
    "DATA.PROFILE_STALE", "DATA.PRODUCTS_STALE", "DATA.MARKET_STALE",
    "ALLOC.MISSING", "ALLOC.UNKNOWN_CLASS", "ALLOC.SUM", "ALLOC.BAND", "ALLOC.GROWTH_CEILING", "ALLOC.NOT_PREFERRED",
    "PROD.UNVERIFIED", "PROD.SUITABILITY", "PROD.CLASS_NOT_ALLOCATED", "PROD.WEIGHTS_MISSING",
    "PROD.SINGLE_CAP", "PROD.FX_CAP",
    "PACK.SECTION_INCOMPLETE", "PACK.SECTION_FLAGGED", "PACK.PRIOR_GATE",
    "TEXT.CLAIM", "TEXT.DISCLAIMER", "TEXT.NUMBERS",
)

# Raised by the service itself when no policy rule can apply.
SYS_INTERNAL = "SYS.INTERNAL"
SYS_POLICY = "SYS.POLICY"

SEVERITY_BY_EFFECT: dict[str, Severity] = {
    "BLOCK": "BLOCKING", "NEEDS_INFO": "BLOCKING", "CONDITION": "MATERIAL", "NOTE": "MINOR",
}


class PolicyError(RuntimeError):
    """The policy file is missing, malformed, incomplete, or not the version the caller expects."""


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rule(_PolicyModel):
    effect: Effect
    description: str


class Thresholds(_PolicyModel):
    escalate_missing_fields: list[str]
    min_horizon_years_by_risk_level: dict[int, float]
    profile_stale_after_days: int = Field(ge=0)
    product_stale_after_days: int = Field(ge=0)
    market_stale_after_days: int = Field(ge=0)
    allocation_sum_tolerance_pct: float = Field(ge=0)
    band_tolerance_pct: float = Field(ge=0)
    growth_ceiling_tolerance_pct: float = Field(ge=0)
    default_max_single_product_pct: float = Field(gt=0, le=100)
    default_max_currency_exposure_pct: float = Field(ge=0, le=100)
    complete_section_statuses: list[str]
    required_prior_gates: list[str]
    required_disclaimer_phrases: list[str]


class RiskPolicy(_PolicyModel):
    notice: str = Field(alias="_notice")
    policy_id: str
    policy_version: str
    thresholds: Thresholds
    rules: dict[str, Rule]


@dataclass(frozen=True)
class LoadedPolicy:
    policy: RiskPolicy
    digest: str  # sha256 of the file bytes, part of every inputs_fingerprint

    @property
    def version(self) -> str:
        return self.policy.policy_version

    @property
    def t(self) -> Thresholds:
        return self.policy.thresholds

    def finding(
        self,
        rule_id: str,
        code: str,
        message: str,
        fields: Optional[list[str]] = None,
        observed: Optional[Union[float, str]] = None,
        threshold: Optional[Union[float, str]] = None,
    ) -> RiskFinding:
        effect = self.policy.rules[rule_id].effect
        return RiskFinding(
            code=code, severity=SEVERITY_BY_EFFECT[effect], effect=effect, rule_id=rule_id,
            policy_version=self.version, fields=fields or [], observed=observed, threshold=threshold, message=message,
        )


def load_policy(path: Optional[Path] = None) -> LoadedPolicy:
    path = path or POLICY_PATH
    try:
        raw_bytes = path.read_bytes()
        policy = RiskPolicy.model_validate(json.loads(raw_bytes))
    except (OSError, ValueError, ValidationError) as e:
        logger.warning("Risk policy could not be loaded: %s", type(e).__name__)
        raise PolicyError("The risk & compliance policy could not be loaded.") from e

    missing = [r for r in RULE_IDS if r not in policy.rules]
    if missing:
        raise PolicyError(f"The risk & compliance policy does not define rules: {', '.join(missing)}.")
    levels = set(policy.thresholds.min_horizon_years_by_risk_level)
    if levels != {1, 2, 3, 4, 5}:
        raise PolicyError("min_horizon_years_by_risk_level must define risk levels 1-5.")
    return LoadedPolicy(policy=policy, digest=hashlib.sha256(raw_bytes).hexdigest())


def field_matches(pattern: str, field_name: str) -> bool:
    """'financial_goals[*].years_to_goal' matches 'financial_goals[Retirement].years_to_goal'."""
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, field_name) is not None
