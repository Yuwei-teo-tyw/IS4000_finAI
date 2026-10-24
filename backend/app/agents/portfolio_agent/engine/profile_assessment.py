"""
Client-profile assessment: completeness, internal consistency, and the
effective risk level used for construction.

Risk appetite (willingness) and risk capacity (financial ability to absorb
losses) are assessed separately and the *lower* of the two governs. The
questionnaire score is cross-checked against the stated appetite. Missing
or contradictory inputs are reported field-by-field with a severity:

  BLOCKING - no portfolio can responsibly be constructed without it
  MATERIAL - portfolios can be built, but a preferred option will not be
             nominated until the RM resolves it
  MINOR    - noted; doesn't change construction
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.agents.portfolio_agent.schemas.client import ClientProfile, FinancialGoal, UpdateTrigger
from app.agents.portfolio_agent.schemas.response import Conflict, MissingInformation
from app.agents.portfolio_agent.taxonomy import (
    RISK_LEVEL_LABELS,
    parse_asset_class,
    parse_risk_appetite,
    parse_risk_capacity,
    resolve_preference,
)

# Reserve coverage below this many months of expenses contradicts a stated
# high risk capacity.
MIN_RESERVE_MONTHS_FOR_HIGH_CAPACITY = 3
# Liabilities above this share of investable assets contradict a stated
# high risk capacity.
MAX_LIABILITY_RATIO_FOR_HIGH_CAPACITY = 0.5
# A drawdown limit below this (%) is inconsistent with an aggressive appetite.
MIN_DRAWDOWN_FOR_AGGRESSIVE_APPETITE = 10.0


@dataclass
class NormalisedGoal:
    goal: str
    priority: Optional[str]
    target_amount: Optional[float]
    currency: Optional[str]
    years_to_goal: Optional[float]


@dataclass
class ProfileAssessment:
    reference_date: date
    missing: list[MissingInformation] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    appetite_level: Optional[int] = None
    score_level: Optional[int] = None
    capacity_level: Optional[int] = None
    # Capacity after the reserve/liability caps below - what actually limits construction.
    capacity_effective: Optional[int] = None
    willingness_level: Optional[int] = None
    effective_level: Optional[int] = None
    effective_basis: Optional[str] = None
    goals: list[NormalisedGoal] = field(default_factory=list)
    shortest_horizon_years: Optional[float] = None
    preferred_classes: Optional[set] = None  # None = no preference stated

    @property
    def is_blocked(self) -> bool:
        return any(m.severity == "BLOCKING" for m in self.missing) or any(
            c.severity == "BLOCKING" for c in self.conflicts
        )

    @property
    def has_material_issues(self) -> bool:
        return any(m.severity == "MATERIAL" for m in self.missing) or any(
            c.severity == "MATERIAL" for c in self.conflicts
        )

    @property
    def effective_label(self) -> Optional[str]:
        return RISK_LEVEL_LABELS.get(self.effective_level) if self.effective_level else None


def _missing(a: ProfileAssessment, field_name: str, severity: str, impact: str) -> None:
    a.missing.append(MissingInformation(field=field_name, severity=severity, impact=impact))


def _conflict(a: ProfileAssessment, fields: list[str], severity: str, description: str, resolution: str) -> None:
    a.conflicts.append(Conflict(fields=fields, severity=severity, description=description, resolution=resolution))


def assess_profile(profile: ClientProfile, trigger: Optional[UpdateTrigger], today: date) -> ProfileAssessment:
    ref = (trigger.effective_date if trigger and trigger.effective_date else None) or today
    a = ProfileAssessment(reference_date=ref)

    _assess_financials(profile, a)
    _assess_risk(profile, a)
    _assess_goals(profile, a)
    _assess_preferences(profile, a)
    _assess_minor_fields(profile, a)
    return a


def _assess_financials(p: ClientProfile, a: ProfileAssessment) -> None:
    if p.base_currency is None:
        _missing(a, "base_currency", "BLOCKING", "Investment amounts and currency exposure cannot be expressed.")
    if p.investable_assets is None:
        _missing(a, "investable_assets", "BLOCKING", "The portfolio value to allocate is unknown.")
    elif p.investable_assets == 0:
        _conflict(a, ["investable_assets"], "BLOCKING", "Investable assets are zero.", "No portfolio can be constructed.")

    if p.total_aum is not None and p.investable_assets is not None and p.investable_assets > p.total_aum:
        _conflict(
            a, ["investable_assets", "total_aum"], "BLOCKING",
            f"investable_assets ({p.investable_assets:,.2f}) exceed total_aum ({p.total_aum:,.2f}).",
            "Construction halted - the RM must confirm which figure is correct.",
        )
    if p.total_aum is not None and p.cash_balance is not None and p.cash_balance > p.total_aum:
        _conflict(
            a, ["cash_balance", "total_aum"], "MATERIAL",
            f"cash_balance ({p.cash_balance:,.2f}) exceeds total_aum ({p.total_aum:,.2f}).",
            "Figures reported as provided; RM to confirm.",
        )
    if p.current_holdings and p.total_aum is not None:
        held = sum(h.market_value for h in p.current_holdings)
        if held > p.total_aum * 1.02:
            _conflict(
                a, ["current_holdings", "total_aum"], "MATERIAL",
                f"Current holdings total {held:,.2f}, above total_aum of {p.total_aum:,.2f}.",
                "Holdings shown for reference only; RM to reconcile.",
            )
    if p.current_asset_allocation:
        total = sum(p.current_asset_allocation.values())
        if abs(total - 100) > 1:
            _conflict(
                a, ["current_asset_allocation"], "MATERIAL",
                f"current_asset_allocation sums to {total:.2f}%, not 100%.",
                "Changes versus current allocation are not reported.",
            )

    if p.minimum_cash_reserve is None and p.monthly_expenses is None:
        _missing(
            a, "minimum_cash_reserve / monthly_expenses", "BLOCKING",
            "The cash reserve that must be ring-fenced from investment cannot be determined.",
        )
    elif p.minimum_cash_reserve is None:
        _missing(
            a, "minimum_cash_reserve", "MATERIAL",
            "Reserve set to 6 months of monthly_expenses as a stated assumption; RM to confirm.",
        )
    if p.monthly_expenses is None:
        _missing(a, "monthly_expenses", "MINOR", "Reserve adequacy (months of expenses covered) cannot be checked.")

    if p.planned_withdrawals is None:
        _missing(
            a, "planned_withdrawals", "MATERIAL",
            "No withdrawals ring-fenced. If the client expects to draw on the portfolio, liquidity may be insufficient.",
        )

    if p.annual_income is None:
        _missing(a, "annual_income", "MINOR", "Ability to replenish losses from income cannot be assessed.")
    elif p.monthly_expenses is not None and p.annual_income < 12 * p.monthly_expenses:
        a.warnings.append(
            "Annual income is below annualised expenses - the client may need to draw on savings, "
            "which reduces risk capacity."
        )

    if p.liabilities is None:
        _missing(a, "liabilities", "MINOR", "Debt obligations were not considered in risk capacity.")


def _assess_risk(p: ClientProfile, a: ProfileAssessment) -> None:
    a.appetite_level = parse_risk_appetite(p.risk_appetite)
    if p.risk_appetite and a.appetite_level is None:
        _conflict(
            a, ["risk_appetite"], "MATERIAL",
            f"risk_appetite '{p.risk_appetite}' is not a recognised label.",
            "Ignored; risk_tolerance_score used instead if available.",
        )
    a.score_level = p.risk_tolerance_score

    if a.appetite_level is None and a.score_level is None:
        _missing(a, "risk_appetite / risk_tolerance_score", "BLOCKING", "Client's willingness to take risk is unknown.")
        willingness = None
    elif a.appetite_level is not None and a.score_level is not None:
        diff = abs(a.appetite_level - a.score_level)
        willingness = min(a.appetite_level, a.score_level)
        if diff >= 2:
            _conflict(
                a, ["risk_appetite", "risk_tolerance_score"], "MATERIAL",
                f"Stated risk appetite '{p.risk_appetite}' (level {a.appetite_level}) contradicts "
                f"risk tolerance score {a.score_level}.",
                f"The more conservative level ({willingness}) is used; RM to reconfirm with the client.",
            )
        elif diff == 1:
            _conflict(
                a, ["risk_appetite", "risk_tolerance_score"], "INFO",
                f"Risk appetite (level {a.appetite_level}) and tolerance score ({a.score_level}) differ by one level.",
                f"The more conservative level ({willingness}) is used.",
            )
    else:
        willingness = a.appetite_level if a.appetite_level is not None else a.score_level

    a.capacity_level = parse_risk_capacity(p.risk_capacity)
    if p.risk_capacity is None:
        _missing(
            a, "risk_capacity", "BLOCKING",
            "Risk capacity (financial ability to absorb losses) must be assessed separately from risk appetite.",
        )
    elif a.capacity_level is None:
        _conflict(
            a, ["risk_capacity"], "BLOCKING",
            f"risk_capacity '{p.risk_capacity}' is not a recognised label.",
            "Construction halted until risk capacity is restated.",
        )

    capacity = a.capacity_level
    if capacity is not None and capacity >= 4:
        reserve = p.emergency_fund if p.emergency_fund is not None else p.minimum_cash_reserve
        if p.monthly_expenses and reserve is not None:
            months = reserve / p.monthly_expenses
            if months < MIN_RESERVE_MONTHS_FOR_HIGH_CAPACITY:
                _conflict(
                    a, ["risk_capacity", "emergency_fund", "monthly_expenses"], "MATERIAL",
                    f"Stated risk capacity '{p.risk_capacity}' but reserves cover only {months:.1f} months of expenses.",
                    "Risk capacity capped at Moderate (3) for construction.",
                )
                capacity = 3
        if p.liabilities is not None and p.investable_assets:
            ratio = p.liabilities / p.investable_assets
            if ratio > MAX_LIABILITY_RATIO_FOR_HIGH_CAPACITY:
                _conflict(
                    a, ["risk_capacity", "liabilities", "investable_assets"], "MATERIAL",
                    f"Stated risk capacity '{p.risk_capacity}' but liabilities are {ratio:.0%} of investable assets.",
                    "Risk capacity capped at Moderate (3) for construction.",
                )
                capacity = min(capacity, 3)

    a.capacity_effective, a.willingness_level = capacity, willingness
    if willingness is not None and capacity is not None:
        a.effective_level = min(willingness, capacity)
        if willingness > capacity:
            a.effective_basis = (
                f"Risk capacity (level {capacity}) is lower than willingness (level {willingness}); capacity governs."
            )
            if willingness - capacity >= 2:
                _conflict(
                    a, ["risk_appetite", "risk_capacity"], "INFO",
                    "Client is willing to take materially more risk than their finances can absorb.",
                    "Portfolios are constrained by risk capacity; RM may wish to discuss expectations.",
                )
        elif capacity > willingness:
            a.effective_basis = (
                f"Risk willingness (level {willingness}) is lower than capacity (level {capacity}); willingness governs."
            )
        else:
            a.effective_basis = f"Risk willingness and capacity agree (level {capacity})."

    if p.maximum_acceptable_drawdown is None:
        _missing(
            a, "maximum_acceptable_drawdown", "MATERIAL",
            "No explicit loss limit - only the risk-level growth ceilings constrain downside.",
        )
    elif (
        a.appetite_level is not None
        and a.appetite_level >= 4
        and p.maximum_acceptable_drawdown < MIN_DRAWDOWN_FOR_AGGRESSIVE_APPETITE
    ):
        _conflict(
            a, ["risk_appetite", "maximum_acceptable_drawdown"], "MATERIAL",
            f"Risk appetite '{p.risk_appetite}' is inconsistent with a maximum acceptable drawdown of "
            f"{p.maximum_acceptable_drawdown}%.",
            "The drawdown limit is applied as a hard constraint; RM to reconfirm.",
        )


def _years_until(ref: date, target: date) -> float:
    return (target - ref).days / 365.25


def _assess_goals(p: ClientProfile, a: ProfileAssessment) -> None:
    goals = list(p.financial_goals or [])
    if not goals and (p.target_amount is not None or p.target_date is not None):
        # Top-level target without a structured goal list.
        goals = [FinancialGoal(goal="Primary investment target", target_amount=p.target_amount, target_date=p.target_date)]

    if not goals:
        _missing(
            a, "financial_goals", "MATERIAL",
            "Investment horizon and goal alignment cannot be assessed; long-term growth option not offered.",
        )
        return

    for g in goals:
        years = g.years_to_goal
        if g.target_date is not None:
            from_date = _years_until(a.reference_date, g.target_date)
            if from_date <= 0:
                _conflict(
                    a, [f"financial_goals[{g.goal}].target_date"], "MATERIAL",
                    f"Goal '{g.goal}' has a target date ({g.target_date}) on or before the review date.",
                    "Goal excluded from horizon calculations; RM to update.",
                )
                from_date = None
            if from_date is not None and years is not None and abs(from_date - years) > 1:
                _conflict(
                    a, [f"financial_goals[{g.goal}]"], "MATERIAL",
                    f"Goal '{g.goal}': years_to_goal ({years}) and target_date ({g.target_date}) disagree.",
                    "The shorter horizon is used.",
                )
                years = min(years, from_date)
            elif from_date is not None and years is None:
                years = round(from_date, 2)
        if years is None:
            _missing(a, f"financial_goals[{g.goal}].years_to_goal", "MATERIAL", "Goal horizon unknown.")
        if g.target_amount is None:
            _missing(a, f"financial_goals[{g.goal}].target_amount", "MINOR", "Goal funding cannot be checked.")
        if g.priority is None:
            _missing(a, f"financial_goals[{g.goal}].priority", "MINOR", "Goal treated as equal priority.")
        if g.currency and p.base_currency and g.currency != p.base_currency:
            a.warnings.append(
                f"Goal '{g.goal}' is denominated in {g.currency}, not the base currency {p.base_currency}; "
                "goal projections ignore FX movements."
            )
        a.goals.append(NormalisedGoal(g.goal, g.priority, g.target_amount, g.currency, years))

    horizons_high = [g.years_to_goal for g in a.goals if g.years_to_goal is not None and g.priority == "High"]
    horizons_all = [g.years_to_goal for g in a.goals if g.years_to_goal is not None]
    # Shortest horizon of any goal: the portfolio must still be suitable when
    # the first goal falls due.
    if horizons_all:
        a.shortest_horizon_years = min(horizons_all)
        if horizons_high and min(horizons_high) > a.shortest_horizon_years:
            a.assumptions.append(
                "The shortest goal horizon (including lower-priority goals) is used to constrain growth exposure."
            )


def _assess_preferences(p: ClientProfile, a: ProfileAssessment) -> None:
    if not p.preferred_asset_classes:
        return
    allowed = set()
    for label in p.preferred_asset_classes:
        resolved = resolve_preference(label)
        if resolved is None:
            _conflict(
                a, ["preferred_asset_classes"], "INFO",
                f"Preferred asset class '{label}' is not recognised.",
                "Ignored; RM to restate using a supported asset class.",
            )
        else:
            allowed |= resolved
    if allowed:
        a.preferred_classes = allowed
        a.assumptions.append(
            "Asset classes outside the client's preferred_asset_classes are excluded from all options."
        )


def _assess_minor_fields(p: ClientProfile, a: ProfileAssessment) -> None:
    if p.age is None:
        _missing(a, "age", "MINOR", "Life-stage considerations not applied.")
    if p.residency is None:
        _missing(a, "residency", "MINOR", "Products with residency restrictions are excluded.")
    if p.accredited_investor is None:
        _missing(a, "accredited_investor", "MINOR", "Products restricted to accredited investors are excluded.")
    if p.maximum_single_asset_allocation is None:
        _missing(a, "maximum_single_asset_allocation", "MINOR", "No per-product concentration limit applied.")
    if p.maximum_currency_exposure is None:
        _missing(a, "maximum_currency_exposure", "MINOR", "Foreign-currency exposure is reported but not limited.")
    if p.current_holdings is None and p.current_asset_allocation is None:
        _missing(a, "current_holdings / current_asset_allocation", "MINOR", "Transition from the current portfolio is not shown.")
    if p.unrealised_gains_losses:
        a.warnings.append(
            "The client has unrealised gains/losses on existing holdings; switching may crystallise them. "
            "Any tax or cost impact should be confirmed before implementation."
        )
    # Unknown asset class labels in current allocation are reported, not guessed.
    if p.current_asset_allocation:
        unknown = [k for k in p.current_asset_allocation if parse_asset_class(k) is None]
        if unknown:
            a.warnings.append(
                f"Current allocation labels not mapped to a known asset class: {', '.join(unknown)}."
            )
