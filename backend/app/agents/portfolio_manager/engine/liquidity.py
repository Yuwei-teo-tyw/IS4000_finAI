"""
Derives the eligible portfolio value from investable_assets.

    eligible = investable_assets
               - reserve still to be funded from investable assets
               - planned withdrawals due within NEAR_TERM_WITHDRAWAL_MONTHS

No double counting: the emergency fund and the minimum cash reserve are the
same pot of money, so the requirement is minimum_cash_reserve (not
reserve + emergency fund), and only the part of it not already held
*outside* investable assets is carved out. Planned withdrawals are a
separate need (spending, not emergencies) and are carved out in addition.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.schemas.response import Conflict, LiquidityPlan, Statement

NEAR_TERM_WITHDRAWAL_MONTHS = 24
DEFAULT_RESERVE_MONTHS = 6


@dataclass
class LiquidityResult:
    plan: LiquidityPlan
    eligible_value: Optional[float]
    conflicts: list[Conflict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


def _months_until(ref: date, d: date) -> float:
    return (d - ref).days / 30.4375


def build_liquidity_plan(p: ClientProfile, a: ProfileAssessment) -> LiquidityResult:
    notes: list[Statement] = []
    assumptions: list[str] = []
    conflicts: list[Conflict] = []

    # --- Reserve requirement ----------------------------------------------
    if p.minimum_cash_reserve is not None:
        requirement = p.minimum_cash_reserve
        notes.append(Statement(
            statement=f"Minimum cash reserve of {requirement:,.2f} specified by the RM.", basis="CLIENT_INPUT"
        ))
    elif p.monthly_expenses is not None:
        requirement = DEFAULT_RESERVE_MONTHS * p.monthly_expenses
        assumptions.append(
            f"Cash reserve assumed at {DEFAULT_RESERVE_MONTHS} months of expenses ({requirement:,.2f}) "
            "because minimum_cash_reserve was not provided."
        )
        notes.append(Statement(
            statement=f"Reserve of {requirement:,.2f} = {DEFAULT_RESERVE_MONTHS} x monthly expenses.", basis="ASSUMPTION"
        ))
    else:
        requirement = None

    held_outside = 0.0
    if p.emergency_fund:
        if p.emergency_fund_included_in_investable_assets is False:
            held_outside = p.emergency_fund
            notes.append(Statement(
                statement=f"Emergency fund of {p.emergency_fund:,.2f} is held outside investable assets and counts "
                          "towards the reserve requirement.",
                basis="CLIENT_INPUT",
            ))
        elif p.emergency_fund_included_in_investable_assets is None:
            assumptions.append(
                f"The emergency fund ({p.emergency_fund:,.2f}) is assumed to be part of investable_assets, so the "
                "reserve is carved out of investable assets. If it is held separately, the eligible portfolio value "
                f"would be up to {min(p.emergency_fund, requirement or 0):,.2f} higher."
            )
        else:
            notes.append(Statement(
                statement="Emergency fund is part of investable assets; it is ring-fenced as the reserve, not added to it.",
                basis="CLIENT_INPUT",
            ))

    reserve_carve = max(0.0, requirement - held_outside) if requirement is not None else None

    # --- Planned withdrawals -----------------------------------------------
    near_term = 0.0
    later = 0.0
    pw = p.planned_withdrawals
    if isinstance(pw, (int, float)) and not isinstance(pw, bool):
        if pw > 0:
            near_term = float(pw)
            assumptions.append(
                f"Planned withdrawals of {pw:,.2f} have no stated timing and are treated as near-term "
                f"(within {NEAR_TERM_WITHDRAWAL_MONTHS} months), so they are excluded from the investment portfolio."
            )
    elif isinstance(pw, list):
        undated = 0
        for w in pw:
            if w.months_from_now is not None:
                months = w.months_from_now
            elif w.expected_date is not None:
                months = _months_until(a.reference_date, w.expected_date)
            else:
                months = None
                undated += 1
            if months is None or months <= NEAR_TERM_WITHDRAWAL_MONTHS:
                near_term += w.amount
            else:
                later += w.amount
        if undated:
            assumptions.append(f"{undated} planned withdrawal(s) without timing are treated as near-term.")
        if later:
            notes.append(Statement(
                statement=f"Withdrawals of {later:,.2f} fall due after {NEAR_TERM_WITHDRAWAL_MONTHS} months; they "
                          "remain invested but favour liquid products.",
                basis="CLIENT_INPUT",
            ))
    if near_term:
        notes.append(Statement(
            statement=f"Near-term planned withdrawals of {near_term:,.2f} are ring-fenced and not invested.",
            basis="CLIENT_INPUT",
        ))

    # --- Eligible value -----------------------------------------------------
    eligible: Optional[float] = None
    if p.investable_assets is not None and reserve_carve is not None:
        eligible = round(p.investable_assets - reserve_carve - near_term, 2)
        notes.append(Statement(
            statement=f"Eligible portfolio value = {p.investable_assets:,.2f} - {reserve_carve:,.2f} (reserve) - "
                      f"{near_term:,.2f} (near-term withdrawals) = {eligible:,.2f}.",
            basis="CALCULATION",
        ))
        if eligible <= 0:
            conflicts.append(Conflict(
                fields=["investable_assets", "minimum_cash_reserve", "planned_withdrawals"],
                severity="BLOCKING",
                description=(
                    f"Reserve ({reserve_carve:,.2f}) and near-term withdrawals ({near_term:,.2f}) consume all "
                    f"investable assets ({p.investable_assets:,.2f})."
                ),
                resolution="No investment portfolio is proposed; all investable assets should stay liquid.",
            ))
            eligible = None
        elif eligible < 0.2 * p.investable_assets:
            notes.append(Statement(
                statement="Less than 20% of investable assets remain after liquidity needs; the investment "
                          "portfolio is small relative to the client's commitments.",
                basis="CALCULATION",
            ))

    plan = LiquidityPlan(
        investable_assets=p.investable_assets,
        minimum_cash_reserve_required=requirement,
        reserve_already_held_outside_investable_assets=held_outside,
        reserve_carved_out=reserve_carve,
        near_term_withdrawals_carved_out=near_term,
        later_withdrawals_not_carved_out=later,
        eligible_portfolio_value=eligible,
        notes=notes,
    )
    return LiquidityResult(plan=plan, eligible_value=eligible, conflicts=conflicts, assumptions=assumptions)
