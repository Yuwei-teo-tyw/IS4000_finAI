"""
Readiness check (step 4 of the advisory workflow): is the confirmed client
context good enough to advise on, and what limits must the advice respect?

Thin by design. The rules are the Portfolio Agent's own:
`assess_profile()` (appetite vs capacity, missing and contradictory
fields) and `build_liquidity_plan()` (reserve, withdrawals, eligible
value). This module only adds the policy's escalations (fields the policy
needs before any advice, stale profile, horizon too short for the risk
level), turns the result into machine-readable constraints, and resolves a
status. It never passes by default.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.agents.portfolio_agent.engine.construction import ConstructionContext
from app.agents.portfolio_agent.engine.liquidity import (
    LiquidityResult,
    build_liquidity_plan,
)
from app.agents.portfolio_agent.engine.profile_assessment import (
    ProfileAssessment,
    assess_profile,
)
from app.agents.portfolio_agent.schemas.client import ClientProfile, UpdateTrigger
from app.agents.portfolio_agent.schemas.response import Conflict, MissingInformation
from app.agents.portfolio_agent.taxonomy import ASSET_CLASS_ORDER
from app.agents.product_recommender.suitability import (
    ScreeningResult,
    near_term_need_months,
)
from app.agents.risk_compliance.config import Settings
from app.agents.risk_compliance.policy import LoadedPolicy, field_matches
from app.agents.risk_compliance.schemas import (
    ClientConstraints,
    EffectiveRisk,
    ReadinessReport,
    ReadinessRequest,
    RiskFinding,
    Status,
)

NEXT_STEP = {"BLOCKED": "BLOCK", "NEEDS_INFO": "CLARIFY", "PASS_WITH_CONDITIONS": "ADVISORY", "PASS": "ADVISORY"}


@dataclass
class ReadinessOutcome:
    assessment: ProfileAssessment
    liquidity: LiquidityResult
    constraints: ClientConstraints
    findings: list[RiskFinding]
    missing: list[MissingInformation]
    conflicts: list[Conflict]


def fingerprint(request: BaseModel, policy_digest: Optional[str]) -> str:
    """sha256 over the canonical request and the policy file, so the same
    inputs under the same policy always give the same fingerprint."""
    payload = {"request": request.model_dump(mode="json"), "policy": policy_digest}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_status(findings: list[RiskFinding], missing: list[MissingInformation], conflicts: list[Conflict]) -> Status:
    """BLOCKED > NEEDS_INFO > PASS_WITH_CONDITIONS > PASS."""
    effects = {f.effect for f in findings}
    if "BLOCK" in effects or any(c.severity == "BLOCKING" for c in conflicts):
        return "BLOCKED"
    if "NEEDS_INFO" in effects or any(m.severity == "BLOCKING" for m in missing):
        return "NEEDS_INFO"
    if (
        "CONDITION" in effects
        or any(m.severity == "MATERIAL" for m in missing)
        or any(c.severity == "MATERIAL" for c in conflicts)
    ):
        return "PASS_WITH_CONDITIONS"
    return "PASS"


def growth_ceiling(level: int, horizon_years: Optional[float]) -> float:
    """The PM's own growth ceiling (risk level, then horizon caps), read from
    ConstructionContext so the two agents cannot drift apart."""
    ctx = ConstructionContext(
        eligible_value=0.0, base_currency="", effective_level=level, horizon_years=horizon_years,
        max_single_pct=None, max_drawdown_pct=None, max_fx_pct=None,
        screening=ScreeningResult(by_class={}, excluded=[]),
    )
    return ctx.growth_ceiling


def _governed_by(a: ProfileAssessment) -> Optional[str]:
    if a.effective_level is None:
        return None
    willingness = min(lv for lv in (a.appetite_level, a.score_level) if lv is not None)
    if a.effective_level < willingness:
        return "capacity"
    if a.capacity_level is not None and a.capacity_level > willingness:
        return "willingness"
    return "agree"


def effective_risk(a: ProfileAssessment) -> EffectiveRisk:
    return EffectiveRisk(
        appetite_level=a.appetite_level, score_level=a.score_level, capacity_level=a.capacity_level,
        effective_level=a.effective_level, effective_label=a.effective_label,
        governed_by=_governed_by(a), basis=a.effective_basis,
    )


def _constraints(p: ClientProfile, a: ProfileAssessment, policy: LoadedPolicy, settings: Settings) -> ClientConstraints:
    preferred = None
    if a.preferred_classes is not None:
        preferred = [ac.value for ac in ASSET_CLASS_ORDER if ac in a.preferred_classes]
    horizon = a.shortest_horizon_years
    return ClientConstraints(
        effective_risk_level=a.effective_level,
        shortest_horizon_years=horizon,
        max_growth_pct=growth_ceiling(a.effective_level, horizon) if a.effective_level else None,
        max_drawdown_pct=p.maximum_acceptable_drawdown,
        max_single_product_pct=p.maximum_single_asset_allocation or policy.t.default_max_single_product_pct,
        max_currency_exposure_pct=(
            p.maximum_currency_exposure if p.maximum_currency_exposure is not None
            else policy.t.default_max_currency_exposure_pct
        ),
        max_lock_in_months=round(horizon * 12, 2) if horizon is not None else None,
        near_term_cash_need_months=near_term_need_months(p, a.reference_date, settings.liquidity_need_months),
        preferred_asset_classes=preferred,
        banned_sectors=list(dict.fromkeys(p.excluded_sectors or [])),
        restricted_products=list(dict.fromkeys(p.restricted_products or [])),
        esg_required=bool(p.esg_preferences and p.esg_preferences.level == "Required"),
    )


def _profile_staleness(profile_as_of: Optional[date], ref: date, policy: LoadedPolicy) -> list[RiskFinding]:
    limit = policy.t.profile_stale_after_days
    if profile_as_of is None:
        return [policy.finding(
            "DATA.PROFILE_STALE", "PROFILE_AS_OF_UNKNOWN",
            "The date the client profile was last confirmed is unknown, so its currency cannot be checked.",
            fields=["profile_as_of"], observed="unknown", threshold=limit,
        )]
    age = (ref - profile_as_of).days
    if age > limit:
        return [policy.finding(
            "DATA.PROFILE_STALE", "PROFILE_STALE",
            f"The client profile was last confirmed {age} days ago; the policy allows {limit}.",
            fields=["profile_as_of"], observed=age, threshold=limit,
        )]
    return []


def assess_readiness(
    p: ClientProfile,
    trigger: Optional[UpdateTrigger],
    reference_date: date,
    profile_as_of: Optional[date],
    policy: LoadedPolicy,
    settings: Settings,
) -> ReadinessOutcome:
    a = assess_profile(p, trigger, reference_date)
    liq = build_liquidity_plan(p, a)
    findings: list[RiskFinding] = []

    for m in a.missing:
        if any(field_matches(pattern, m.field) for pattern in policy.t.escalate_missing_fields):
            findings.append(policy.finding(
                "READY.REQUIRED_FIELD", "MISSING_REQUIRED_FIELD",
                f"{m.field} is required by policy before any advice. {m.impact}",
                fields=[m.field], observed="missing",
            ))

    findings += _profile_staleness(profile_as_of, a.reference_date, policy)

    if a.effective_level is not None and a.shortest_horizon_years is not None:
        minimum = policy.t.min_horizon_years_by_risk_level[a.effective_level]
        if a.shortest_horizon_years < minimum:
            findings.append(policy.finding(
                "READY.HORIZON_VS_RISK", "HORIZON_TOO_SHORT_FOR_RISK",
                f"The shortest goal horizon ({a.shortest_horizon_years:g} years) is below the {minimum:g} years "
                f"the policy expects for risk level {a.effective_level} ({a.effective_label}).",
                fields=["financial_goals", "risk_appetite", "risk_capacity"],
                observed=a.shortest_horizon_years, threshold=minimum,
            ))

    return ReadinessOutcome(
        assessment=a, liquidity=liq, constraints=_constraints(p, a, policy, settings), findings=findings,
        missing=list(a.missing), conflicts=list(a.conflicts) + list(liq.conflicts),
    )


def check_readiness(req: ReadinessRequest, policy: LoadedPolicy, settings: Settings, now: datetime) -> ReadinessReport:
    out = assess_readiness(req.client_profile, req.trigger, req.reference_date, req.profile_as_of, policy, settings)
    status = resolve_status(out.findings, out.missing, out.conflicts)
    return ReadinessReport(
        status=status, next_step=NEXT_STEP[status],
        request_id=req.request_id, client_id=req.client_id,
        findings=out.findings, missing_information=out.missing, conflicts=out.conflicts,
        constraints=out.constraints,
        effective_risk=effective_risk(out.assessment),
        eligible_value=out.liquidity.eligible_value, liquidity=out.liquidity.plan,
        assumptions=out.assessment.assumptions + out.liquidity.assumptions,
        inputs_fingerprint=fingerprint(req, policy.digest),
        policy_id=policy.policy.policy_id, policy_version=policy.version, computed_at=now,
    )
