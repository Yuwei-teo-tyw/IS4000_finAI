"""
Portfolio metrics for a constructed option. Pure functions over the
positions, product data and house assumptions; every metric is None when the
inputs needed to compute it reliably are missing, rather than filled with
a guess.
"""
from dataclasses import dataclass
from typing import Optional

from app.agents.portfolio_manager.engine.construction import BuiltOption, ConstructionContext, foreign_currency_exposure, stress_drawdown
from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.response import ConstraintCheck, GoalAlignment, PortfolioMetrics, ScenarioOutcome
from app.agents.portfolio_manager.assumptions import CapitalMarketAssumptions
from app.agents.portfolio_manager.schemas.upstream import ProductCandidate
from app.agents.portfolio_manager.taxonomy import HIGH_LIQUIDITY, AssetClass, Liquidity, risk_label_for_stress_drawdown

CONSTRAINT_TOLERANCE = 0.01


@dataclass
class ExpectedReturn:
    value: Optional[float]
    basis: Optional[str]


def product_expected_return(prod: ProductCandidate, ac: AssetClass, cma: CapitalMarketAssumptions) -> ExpectedReturn:
    """Annual return assumption net of the management fee.

    Cash and fixed income: current (illustrative) yield less fee - an
    approximation of hold-to-maturity return that ignores defaults, rate moves
    and reinvestment. Everything else: the Portfolio Manager's house long-term
    assumption for the asset class less fee. The Market Researcher publishes no
    return forecasts, so none are attributed to it.
    """
    if prod.management_fee is None:
        return ExpectedReturn(None, "Management fee unavailable, so a net return assumption cannot be formed.")
    fee = prod.management_fee
    if ac in (AssetClass.CASH, AssetClass.FIXED_INCOME):
        y = prod.yield_to_maturity if prod.yield_to_maturity is not None else prod.distribution_yield
        if y is None:
            return ExpectedReturn(None, "No yield data available.")
        kind = "yield to maturity" if prod.yield_to_maturity is not None else "distribution yield"
        return ExpectedReturn(round(y - fee, 2), f"Product {kind} ({y}%) less management fee ({fee}%); not guaranteed.")
    lt = cma.long_term_expected_return.get(ac.value)
    if lt is None:
        return ExpectedReturn(None, f"No house return assumption for {ac.value}.")
    return ExpectedReturn(
        round(lt - fee, 2),
        f"{cma.label}: {ac.value} {lt}% p.a. ({cma.horizon}) less management fee ({fee}%); an assumption, not a "
        "forecast or guarantee.",
    )


def compute_metrics(
    built: BuiltOption, ctx: ConstructionContext, cma: CapitalMarketAssumptions
) -> tuple[PortfolioMetrics, dict[str, ExpectedReturn]]:
    positions = built.positions
    value = ctx.eligible_value
    notes = [
        "All metrics are programmatic calculations on illustrative upstream data; none are guarantees.",
        "Volatility and stress drawdown are weighted sums of product figures, i.e. they assume perfect "
        "correlation (no diversification benefit) and are conservative upper-bound estimates.",
    ]
    exp = {p.sp.product_id: product_expected_return(p.sp.product, p.sp.asset_class, cma) for p in positions}

    def weighted(getter) -> Optional[float]:
        vals = [getter(p) for p in positions]
        if any(v is None for v in vals):
            return None
        return round(sum(p.pct * v for p, v in zip(positions, vals)) / 100, 2)

    expected = weighted(lambda p: exp[p.sp.product_id].value)
    if expected is None:
        notes.append("Expected return is null because at least one holding lacks a supportable return assumption.")
    vol = weighted(lambda p: p.sp.product.volatility)
    dd = stress_drawdown(positions)
    fee_pct = weighted(lambda p: p.sp.product.management_fee)
    txn = None
    if all(p.sp.product.transaction_fee is not None for p in positions):
        txn = round(sum(p.amount * p.sp.product.transaction_fee / 100 for p in positions), 2)

    liq = None
    if all(p.sp.product.liquidity is not None for p in positions):
        liq = round(sum(p.pct for p in positions if Liquidity(p.sp.product.liquidity) in HIGH_LIQUIDITY), 2)

    geo = _look_through(positions, lambda prod: prod.geographic_exposure)
    sectors = _look_through(positions, lambda prod: prod.sector_exposure)
    if geo is None or sectors is None:
        notes.append("Geographic/sector look-through is null where any holding lacks that breakdown.")

    hhi = sum((p.pct / 100) ** 2 for p in positions)
    if any(p.sp.asset_class in (AssetClass.HEDGE_FUNDS, AssetClass.PRIVATE_MARKETS) for p in positions):
        notes.append("Hedge fund and private market risk figures are illustrative and may understate true risk "
                     "(smoothed or appraisal-based pricing).")

    metrics = PortfolioMetrics(
        expected_annual_return_pct=expected,
        estimated_volatility_pct=vol,
        estimated_stress_drawdown_pct=round(dd, 2) if dd is not None else None,
        growth_asset_share_pct=round(built.growth_share(), 2),
        estimated_annual_fee_pct=fee_pct,
        estimated_annual_fee_amount=round(value * fee_pct / 100, 2) if fee_pct is not None else None,
        estimated_one_off_transaction_cost=txn,
        high_liquidity_share_pct=liq,
        foreign_currency_exposure_pct=round(foreign_currency_exposure(positions, ctx.base_currency), 2),
        number_of_products=len(positions),
        number_of_asset_classes=len(built.class_weights()),
        effective_number_of_holdings=round(1 / hhi, 2) if hhi > 0 else None,
        geographic_exposure_pct=geo,
        sector_exposure_pct=sectors,
        calculation_notes=notes,
    )
    return metrics, exp


def _look_through(positions, getter) -> Optional[dict[str, float]]:
    """Portfolio exposure = sum over holdings of weight x product breakdown.
    Null rather than partial when any holding lacks the breakdown."""
    out: dict[str, float] = {}
    for p in positions:
        breakdown = getter(p.sp.product)
        if not breakdown:
            return None
        total = sum(v for v in breakdown.values() if v)
        if total <= 0:
            return None
        for k, v in breakdown.items():
            if v:
                # Normalise in case a product's breakdown doesn't sum to exactly 100.
                out[k] = out.get(k, 0.0) + p.pct * v / total
    return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def risk_level(metrics: PortfolioMetrics) -> Optional[str]:
    if metrics.estimated_stress_drawdown_pct is None:
        return None
    _, label = risk_label_for_stress_drawdown(metrics.estimated_stress_drawdown_pct)
    return label


def scenario_outcomes(
    built: BuiltOption, value: float, cma: CapitalMarketAssumptions, recession_prob_12m: Optional[float]
) -> list[ScenarioOutcome]:
    """Portfolio return under each house stress scenario. Only the recession
    scenario carries a probability - the Market Researcher's 12-month yield-
    curve estimate; the others are not assigned one rather than invented."""
    out = []
    weights = built.class_weights()
    for sc in cma.scenarios:
        if all(ac.value in sc.asset_class_returns for ac in weights):
            r = round(sum(w * sc.asset_class_returns[ac.value] for ac, w in weights.items()) / 100, 2)
            change = round(value * r / 100, 2)
        else:
            r, change = None, None
        out.append(ScenarioOutcome(
            scenario=sc.name,
            probability=recession_prob_12m if sc.uses_recession_probability else None,
            horizon=sc.horizon, portfolio_return_pct=r, portfolio_value_change=change, basis="ASSUMPTION",
        ))
    return out


def goal_alignment(
    value: float, expected: Optional[float], a: ProfileAssessment, base_currency: str
) -> list[GoalAlignment]:
    out = []
    for g in a.goals:
        common = dict(goal=g.goal, priority=g.priority, target_amount=g.target_amount, years_to_goal=g.years_to_goal)
        if g.target_amount is None or g.years_to_goal is None:
            out.append(GoalAlignment(**common, projected_value_base_case=None, status="NOT_ASSESSABLE",
                                     note="Target amount or horizon missing."))
            continue
        if g.currency and g.currency != base_currency:
            out.append(GoalAlignment(**common, projected_value_base_case=None, status="NOT_ASSESSABLE",
                                     note=f"Goal is in {g.currency}; FX projections are not modelled."))
            continue
        if expected is None:
            out.append(GoalAlignment(**common, projected_value_base_case=None, status="NOT_ASSESSABLE",
                                     note="No supportable expected-return assumption for this option."))
            continue
        projected = round(value * (1 + expected / 100) ** g.years_to_goal, 2)
        status = "ON_TRACK" if projected >= g.target_amount else "SHORTFALL"
        gap = projected - g.target_amount
        out.append(GoalAlignment(
            **common, projected_value_base_case=projected, status=status,
            note=(
                f"Illustrative compound projection at {expected}% p.a. over {g.years_to_goal:g} years "
                f"({'surplus' if gap >= 0 else 'shortfall'} of {abs(gap):,.2f}). Assumes the whole eligible "
                "portfolio serves this goal, no further contributions or withdrawals, and returns that are "
                "not guaranteed; a bear-case path could fall well short."
            ),
        ))
    return out


def constraint_checks(
    built: BuiltOption, metrics: PortfolioMetrics, ctx: ConstructionContext
) -> list[ConstraintCheck]:
    checks = []
    max_pos = max((p.pct for p in built.positions), default=0.0)
    if ctx.max_single_pct is None:
        checks.append(ConstraintCheck(constraint="Maximum single-product allocation", limit=None, actual=max_pos,
                                      status="NOT_APPLICABLE", detail="No limit provided."))
    else:
        ok = max_pos <= ctx.max_single_pct + CONSTRAINT_TOLERANCE
        checks.append(ConstraintCheck(
            constraint="Maximum single-product allocation", limit=ctx.max_single_pct, actual=max_pos,
            status="PASS" if ok else "FAIL",
            detail=f"Largest position is {max_pos:.2f}% of the portfolio.",
        ))

    dd = metrics.estimated_stress_drawdown_pct
    if ctx.max_drawdown_pct is None:
        checks.append(ConstraintCheck(constraint="Maximum acceptable drawdown", limit=None, actual=dd,
                                      status="NOT_APPLICABLE", detail="No limit provided."))
    elif dd is None:
        checks.append(ConstraintCheck(
            constraint="Maximum acceptable drawdown", limit=ctx.max_drawdown_pct, actual=None, status="UNVERIFIED",
            detail="Drawdown data missing for at least one product; compliance cannot be verified.",
        ))
    else:
        ok = dd <= ctx.max_drawdown_pct + CONSTRAINT_TOLERANCE
        checks.append(ConstraintCheck(
            constraint="Maximum acceptable drawdown", limit=ctx.max_drawdown_pct, actual=dd,
            status="PASS" if ok else "FAIL",
            detail="Estimated stress drawdown (historical worst-case of each product, assumed simultaneous).",
        ))

    fx = metrics.foreign_currency_exposure_pct
    if ctx.max_fx_pct is None:
        checks.append(ConstraintCheck(constraint="Maximum currency exposure", limit=None, actual=fx,
                                      status="NOT_APPLICABLE", detail="No limit provided; exposure reported only."))
    else:
        ok = fx <= ctx.max_fx_pct + CONSTRAINT_TOLERANCE
        checks.append(ConstraintCheck(
            constraint="Maximum currency exposure", limit=ctx.max_fx_pct, actual=fx, status="PASS" if ok else "FAIL",
            detail="Unhedged non-base-currency products only; FX exposure inside base-currency funds is not modelled.",
        ))

    g = metrics.growth_asset_share_pct
    ok = g <= ctx.growth_ceiling + CONSTRAINT_TOLERANCE
    checks.append(ConstraintCheck(
        constraint="Growth-asset ceiling (risk level and horizon rule)", limit=ctx.growth_ceiling, actual=g,
        status="PASS" if ok else "FAIL",
        detail=f"Prototype house rule for effective risk level {ctx.effective_level} and the client's horizon.",
    ))
    checks.append(ConstraintCheck(
        constraint="Reserves and near-term withdrawals ring-fenced", limit=None, actual=None, status="PASS",
        detail="Eligible portfolio value already excludes the cash reserve and near-term withdrawals.",
    ))
    return checks
