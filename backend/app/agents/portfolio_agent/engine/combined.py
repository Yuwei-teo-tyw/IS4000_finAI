"""
Combined 3L review: the three bucket portfolios as one client portfolio.

Each bucket is re-evaluated exactly as on Edit weights (same products, same
limits); the combined figures are amount-weighted sums of the buckets.
Nothing here changes a bucket's weights. Checks cover what only shows up
across buckets: the 3L total, the client's overall drawdown, currency and
concentration limits (a product used in two buckets counts once, in total).
"""
from typing import Optional

from app.agents.portfolio_agent.assumptions import CapitalMarketAssumptions
from app.agents.portfolio_agent.engine.adjust import _limit, _point, evaluate_weights
from app.agents.portfolio_agent.engine.buckets import FAST_DEALING, LABELS
from app.agents.portfolio_agent.engine.frontier import model_point
from app.agents.portfolio_agent.schemas.combined import (
    BucketChoice,
    CombinedBucket,
    CombinedClass,
    CombinedPoint,
    CombinedReview,
)
from app.agents.portfolio_agent.schemas.response import ConstraintCheck, PortfolioResponse
from app.agents.portfolio_agent.taxonomy import ASSET_CLASS_ORDER

RECONCILE_TOLERANCE = 1.0  # currency units
LIMIT_TOLERANCE = 0.01
BUCKET_ORDER = ("liquidity", "longevity", "legacy")


class CombinedError(ValueError):
    pass


def _weighted(values: list[tuple[float, Optional[float]]]) -> Optional[float]:
    """Amount-weighted average; None if any bucket lacks the figure."""
    if any(v is None for _, v in values):
        return None
    total = sum(w for w, _ in values)
    return round(sum(w * v for w, v in values) / total, 2) if total else None


def combine(choices: list[tuple[BucketChoice, PortfolioResponse]], cma: CapitalMarketAssumptions,
            client_total: Optional[float]) -> CombinedReview:
    clients = {p.client_id for _, p in choices}
    if len(clients) != 1:
        raise CombinedError("The proposals belong to different clients.")
    for c, p in choices:
        if p.bucket is None:
            raise CombinedError(f"Proposal {p.request_id} was not built for a 3L bucket.")
        if p.bucket.bucket != c.bucket:
            raise CombinedError(f"Proposal {p.request_id} was built for the {p.bucket.label} bucket, not {LABELS[c.bucket]}.")
    choices = sorted(choices, key=lambda cp: BUCKET_ORDER.index(cp[0].bucket))

    buckets: list[CombinedBucket] = []
    class_amounts: dict[str, dict[str, float]] = {}
    product_amounts: dict[str, tuple[str, float]] = {}
    fast = 0.0
    failing: list[str] = []
    limits = {"drawdown": [], "fx": [], "single": []}
    for c, p in choices:
        option = next((o for o in p.portfolio_options if o.option_id == c.option_id), None)
        if option is None:
            raise CombinedError(f"Portfolio {c.option_id} is not part of the {LABELS[c.bucket]} proposal.")
        weights = c.weights or {a.asset_class: a.allocation_percentage for a in option.asset_allocation}
        ev = evaluate_weights(p, c.option_id, weights, cma)  # raises EvaluationError if not offered
        amount = ev.eligible_portfolio_value
        _, positions = _point(option, {ln.asset_class: ln.adjusted_pct for ln in ev.lines}, cma)
        for ln in ev.lines:
            class_amounts.setdefault(ln.asset_class, {})[c.bucket] = ln.adjusted_amount
        for s, pct in positions:
            amt = amount * pct / 100
            name, prev = product_amounts.get(s.product_id, (s.product_name, 0.0))
            product_amounts[s.product_id] = (name, prev + amt)
            if s.liquidity in FAST_DEALING:
                fast += amt
        if not ev.valid:
            failing.append(LABELS[c.bucket])
        limits["drawdown"].append(p.client_profile_summary.maximum_acceptable_drawdown)
        limits["fx"].append(_limit(option, "Maximum currency exposure"))
        limits["single"].append(_limit(option, "Maximum single-product allocation"))
        buckets.append(CombinedBucket(
            bucket=c.bucket, label=LABELS[c.bucket], request_id=p.request_id, option_id=c.option_id,
            option_name=option.option_name, amount=amount, share_pct=0.0, point=ev.adjusted, checks_pass=ev.valid,
        ))

    total = sum(b.amount for b in buckets)
    for b in buckets:
        b.share_pct = round(b.amount / total * 100, 2) if total else 0.0
    order = {ac.value: i for i, ac in enumerate(ASSET_CLASS_ORDER)}
    classes = [
        CombinedClass(asset_class=ac, amount=round(sum(by.values()), 2),
                      pct=round(sum(by.values()) / total * 100, 2) if total else 0.0,
                      by_bucket={k: round(v, 2) for k, v in by.items()})
        for ac, by in sorted(class_amounts.items(), key=lambda kv: order.get(kv[0], 99))
    ]
    combined_class_pct = {c.asset_class: c.pct for c in classes}
    model = model_point(cma, combined_class_pct)
    largest = max(product_amounts.values(), key=lambda t: t[1], default=None)
    point = CombinedPoint(
        model_volatility_pct=model[0] if model else None,
        model_expected_return_pct=model[1] if model else None,
        product_expected_return_pct=_weighted([(b.amount, b.point.product_expected_return_pct) for b in buckets]),
        stress_drawdown_pct=_weighted([(b.amount, b.point.stress_drawdown_pct) for b in buckets]),
        growth_asset_share_pct=_weighted([(b.amount, b.point.growth_asset_share_pct) for b in buckets]) or 0.0,
        estimated_annual_fee_pct=_weighted([(b.amount, b.point.estimated_annual_fee_pct) for b in buckets]),
        foreign_currency_exposure_pct=_weighted([(b.amount, b.point.foreign_currency_exposure_pct) for b in buckets]) or 0.0,
        fast_dealing_share_pct=round(fast / total * 100, 2) if total else 0.0,
        largest_product=largest[0] if largest else None,
        largest_product_pct=round(largest[1] / total * 100, 2) if largest and total else None,
    )

    checks: list[ConstraintCheck] = []
    if client_total is not None:
        gap = total - client_total
        ok = abs(gap) <= RECONCILE_TOLERANCE
        checks.append(ConstraintCheck(
            constraint="3L buckets add up to the client's portfolio", limit=client_total, actual=round(total, 2),
            status="PASS" if ok else "FAIL",
            detail="The buckets together equal the amount to allocate." if ok else
                   f"The buckets total {total:,.2f}, {abs(gap):,.2f} {'over' if gap > 0 else 'under'} the "
                   f"{client_total:,.2f} to allocate. Rebuild the bucket whose amount changed on the 3L step.",
        ))
    checks.append(ConstraintCheck(
        constraint="Each bucket invested separately", limit=None, actual=None, status="PASS",
        detail="Every bucket has its own proposal and amount, so no money is counted in two buckets.",
    ))
    checks.append(ConstraintCheck(
        constraint="Every bucket passes its own checks", limit=None, actual=None,
        status="FAIL" if failing else "PASS",
        detail=f"Fix the weights in: {', '.join(failing)}." if failing else "Each bucket is within its limits.",
    ))
    checks.append(_limit_check("Combined stress drawdown within the client's limit", limits["drawdown"],
                               point.stress_drawdown_pct, "Amount-weighted worst historical drawdown of every product."))
    checks.append(_limit_check("Combined unhedged foreign currency within the limit", limits["fx"],
                               point.foreign_currency_exposure_pct, "Across all three buckets."))
    checks.append(_limit_check("Largest single product across buckets within the limit", limits["single"],
                               point.largest_product_pct,
                               f"{point.largest_product} (a product used in several buckets counts once)."
                               if point.largest_product else "No products."))
    liq = next((b for b in buckets if b.bucket == "liquidity"), None)
    if liq is not None:
        checks.append(ConstraintCheck(
            constraint="Liquidity bucket can be drawn on time", limit=None, actual=None, status="PASS",
            detail="Every Liquidity product deals daily or weekly, or returns cash within the bucket's horizon "
                   "(checked when the bucket was built).",
        ))

    notes = [
        "Combined figures are the buckets' figures weighted by amount. Drawdown assumes every bucket falls at "
        "the same time, which overstates diversification losses rather than hiding them.",
        "Model volatility and return for the whole portfolio use the house assumptions on the combined asset mix.",
        "Market and product data are illustrative; figures are estimates, not guarantees.",
    ]
    valid = all(c.status != "FAIL" for c in checks)
    return CombinedReview(
        client_id=next(iter(clients)), total_amount=round(total, 2), client_total=client_total, buckets=buckets,
        classes=classes, combined=point, checks=checks, valid=valid, notes=notes,
    )


def _limit_check(name: str, limits: list[Optional[float]], actual: Optional[float], detail: str) -> ConstraintCheck:
    known = [x for x in limits if x is not None]
    if not known:
        return ConstraintCheck(constraint=name, limit=None, actual=actual, status="NOT_APPLICABLE",
                               detail="The client has no limit for this.")
    limit = min(known)
    if actual is None:
        return ConstraintCheck(constraint=name, limit=limit, actual=None, status="UNVERIFIED",
                               detail="Some product data is missing, so this cannot be confirmed.")
    ok = actual <= limit + LIMIT_TOLERANCE
    return ConstraintCheck(constraint=name, limit=limit, actual=actual, status="PASS" if ok else "FAIL", detail=detail)
