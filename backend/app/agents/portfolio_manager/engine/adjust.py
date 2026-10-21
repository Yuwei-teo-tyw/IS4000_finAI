"""
Re-evaluates an IC's adjusted asset-class weights for one proposed portfolio.

The adjusted portfolio keeps the proposal's products: each product moves with
its asset class (its share within the class is unchanged). Metrics use the
same methods as the proposal (product data, net of fees), and the same client
limits the proposal was checked against. Nothing here changes a weight the
IC did not change.
"""
from typing import Optional

from app.agents.portfolio_manager.assumptions import CapitalMarketAssumptions
from app.agents.portfolio_manager.engine.frontier import efficient_frontier, model_point
from app.agents.portfolio_manager.schemas.adjust import (
    ClassLine,
    FrontierOut,
    PortfolioPoint,
    WeightEvaluation,
)
from app.agents.portfolio_manager.schemas.response import ConstraintCheck, PortfolioOption, PortfolioResponse
from app.agents.portfolio_manager.taxonomy import GROWTH_WEIGHT, parse_asset_class

TOTAL_TOLERANCE_PP = 0.01
# IC house rule from the SAA builder: each class may move at most this far from the proposal.
MAX_CLASS_DEVIATION_PP = 5.0
LIMIT_TOLERANCE = 0.01


class EvaluationError(ValueError):
    pass


def _growth_weight(asset_class: str) -> float:
    ac = parse_asset_class(asset_class)
    return GROWTH_WEIGHT.get(ac, 0.0) if ac else 0.0


def _point(option: PortfolioOption, class_pct: dict[str, float], cma: CapitalMarketAssumptions) -> tuple[PortfolioPoint, list]:
    """Metrics for `class_pct`, scaling the option's products within each class."""
    original_class = {a.asset_class: a.allocation_percentage for a in option.asset_allocation}
    positions = []  # (selection, new pct)
    for s in option.product_selections:
        base = original_class.get(s.asset_class) or 0
        share = s.allocation_percentage / base if base else 0
        positions.append((s, class_pct.get(s.asset_class, 0.0) * share))

    def weighted(getter) -> Optional[float]:
        held = [(pct, getter(s)) for s, pct in positions if pct > 0]
        if any(v is None for _, v in held):
            return None
        return round(sum(pct * v for pct, v in held) / 100, 2)

    model = model_point(cma, class_pct)
    point = PortfolioPoint(
        model_volatility_pct=model[0] if model else None,
        model_expected_return_pct=model[1] if model else None,
        product_expected_return_pct=weighted(lambda s: s.expected_return_assumption),
        stress_drawdown_pct=weighted(lambda s: abs(s.details.maximum_drawdown) if s.details.maximum_drawdown is not None else None),
        growth_asset_share_pct=round(sum(w * _growth_weight(ac) for ac, w in class_pct.items()), 2),
        estimated_annual_fee_pct=weighted(lambda s: s.management_fee),
        foreign_currency_exposure_pct=round(sum(
            pct for s, pct in positions if s.currency != (option.base_currency or s.currency) and s.currency_hedged is not True
        ), 2),
    )
    return point, positions


def _limit(option: PortfolioOption, prefix: str) -> Optional[float]:
    return next((c.limit for c in option.constraint_checks if c.constraint.startswith(prefix)), None)


def evaluate_weights(
    proposal: PortfolioResponse, option_id: str, weights: dict[str, float], cma: CapitalMarketAssumptions,
) -> WeightEvaluation:
    option = next((o for o in proposal.portfolio_options if o.option_id == option_id), None)
    if option is None:
        raise EvaluationError(f"Option {option_id} is not part of proposal {proposal.request_id}.")
    if option.suitability_status not in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS") or not option.eligible_portfolio_value:
        raise EvaluationError(f"Option {option_id} was not offered, so it cannot be adjusted.")
    original = {a.asset_class: a.allocation_percentage for a in option.asset_allocation}
    unknown = sorted(set(weights) - set(original))
    if unknown:
        raise EvaluationError(f"Asset classes not in portfolio {option_id}: {', '.join(unknown)}. "
                              "Weights can only be moved between the portfolio's own asset classes.")
    adjusted = {ac: float(weights.get(ac, original[ac])) for ac in original}
    value = option.eligible_portfolio_value

    orig_point, _ = _point(option, original, cma)
    adj_point, positions = _point(option, adjusted, cma)

    checks: list[ConstraintCheck] = []
    total = sum(adjusted.values())
    negatives = [ac for ac, w in adjusted.items() if w < 0]
    checks.append(ConstraintCheck(
        constraint="No negative weights", limit=0, actual=min(adjusted.values()) if adjusted else 0,
        status="FAIL" if negatives else "PASS",
        detail=f"Negative: {', '.join(negatives)}." if negatives else "Every weight is zero or more.",
    ))
    checks.append(ConstraintCheck(
        constraint="Weights total 100%", limit=100, actual=round(total, 4),
        status="PASS" if abs(total - 100) <= TOTAL_TOLERANCE_PP else "FAIL",
        detail="Fully invested." if abs(total - 100) <= TOTAL_TOLERANCE_PP else
        f"{'Over' if total > 100 else 'Under'} by {abs(total - 100):.2f} points.",
    ))
    far = [ac for ac in original if abs(adjusted[ac] - original[ac]) > MAX_CLASS_DEVIATION_PP + 1e-9]
    checks.append(ConstraintCheck(
        constraint=f"Each class within {MAX_CLASS_DEVIATION_PP:g} points of the proposal", limit=MAX_CLASS_DEVIATION_PP,
        actual=round(max((abs(adjusted[ac] - original[ac]) for ac in original), default=0), 2),
        status="FAIL" if far else "PASS",
        detail=f"Too far: {', '.join(far)}." if far else "All classes within the band (IC rule from the SAA builder).",
    ))

    def limit_check(name: str, prefix: str, actual: Optional[float], unit_detail: str):
        lim = _limit(option, prefix)
        if lim is None:
            checks.append(ConstraintCheck(constraint=name, limit=None, actual=actual, status="NOT_APPLICABLE",
                                          detail="No limit for this client."))
        elif actual is None:
            checks.append(ConstraintCheck(constraint=name, limit=lim, actual=None, status="UNVERIFIED",
                                          detail="Data missing for at least one product; cannot verify."))
        else:
            ok = actual <= lim + LIMIT_TOLERANCE
            checks.append(ConstraintCheck(constraint=name, limit=lim, actual=actual, status="PASS" if ok else "FAIL",
                                          detail=unit_detail if ok else f"{unit_detail} Exceeds the client's limit."))

    limit_check("Maximum acceptable drawdown", "Maximum acceptable drawdown", adj_point.stress_drawdown_pct,
                "Estimated stress drawdown (each product's worst historical drawdown, assumed simultaneous).")
    limit_check("Growth-asset ceiling", "Growth-asset ceiling", adj_point.growth_asset_share_pct,
                "Equities, hedge funds and private markets combined, against the client's risk level and horizon.")
    limit_check("Maximum currency exposure", "Maximum currency exposure", adj_point.foreign_currency_exposure_pct,
                "Unhedged foreign-currency products.")
    limit_check("Maximum single-product allocation", "Maximum single-product allocation",
                round(max((pct for _, pct in positions), default=0), 2), "Largest single product.")

    below_min = [s.product_name for s, pct in positions
                 if pct > 0 and s.details.minimum_investment and value * pct / 100 < s.details.minimum_investment - 0.005]
    checks.append(ConstraintCheck(
        constraint="Product minimum investments", limit=None, actual=None,
        status="FAIL" if below_min else "PASS",
        detail=f"Below the product's minimum: {', '.join(below_min)}." if below_min else "Every product meets its minimum.",
    ))

    frontier, limitation = None, None
    holdable = sorted({c.asset_class for c in proposal.candidate_products if c.screening_status != "EXCLUDED"})
    f = efficient_frontier(cma, holdable)
    if f is None:
        limitation = ("No efficient frontier: the house assumptions do not give an expected return, volatility and "
                      "correlation for every asset class this client can hold.")
    else:
        frontier = FrontierOut(
            asset_classes=f.asset_classes,
            points=[{"volatility_pct": p.volatility_pct, "expected_return_pct": p.expected_return_pct, "weights": p.weights}
                    for p in f.points],
            model_label=f"{cma.label}: long-term expected returns (before fees), volatilities and correlations",
            method="Long-only, fully invested mean-variance frontier over the asset classes this client can hold; "
                   "solved exactly for each target return.",
        )

    def class_avg(ac: str, getter) -> Optional[float]:
        sels = [s for s in option.product_selections if s.asset_class == ac]
        vals = [getter(s) for s in sels]
        if not sels or any(v is None for v in vals):
            return None
        total_pct = sum(s.allocation_percentage for s in sels)
        return round(sum(s.allocation_percentage * v for s, v in zip(sels, vals)) / total_pct, 2) if total_pct else None

    lines = [ClassLine(
        asset_class=ac, original_pct=original[ac], adjusted_pct=round(adjusted[ac], 4),
        adjusted_amount=round(value * adjusted[ac] / 100, 2), change_pp=round(adjusted[ac] - original[ac], 4),
        expected_return_pct=class_avg(ac, lambda s: s.expected_return_assumption),
        stress_drawdown_pct=class_avg(ac, lambda s: abs(s.details.maximum_drawdown) if s.details.maximum_drawdown is not None else None),
        model_volatility_pct=cma.volatility.get(ac),
    ) for ac in original]
    notes = [
        "Products keep their share within each asset class; only the class weights you changed move.",
        "Frontier and its points use class-level house assumptions (before fees); product-level expected return "
        "uses the selected products' own data, net of fees, as in the proposal.",
    ]
    return WeightEvaluation(
        request_id=proposal.request_id, option_id=option.option_id, option_name=option.option_name,
        eligible_portfolio_value=value, lines=lines, original=orig_point, adjusted=adj_point,
        frontier=frontier, frontier_limitation=limitation, checks=checks,
        valid=all(c.status in ("PASS", "NOT_APPLICABLE") for c in checks), notes=notes,
    )
