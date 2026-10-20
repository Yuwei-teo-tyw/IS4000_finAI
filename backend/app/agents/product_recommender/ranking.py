"""
Ranks products that already passed the suitability gate.

Each component is a named, bounded number, so the PS can see why a product
ranked where it did. Ties break by product_id, so the order is reproducible.

FORBIDDEN INPUTS: management_fee, transaction_fee, any other cost or
commission field, and the issuer. Fees are shown to the PS for information
only and must never move a product up or down this list.
"""
import re
from dataclasses import dataclass
from typing import Optional

from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.taxonomy import GROWTH_WEIGHT, AssetClass
from app.agents.product_recommender.schemas import HouseView
from app.agents.product_recommender.suitability import ScreenedProduct

HOUSE_VIEW_POINTS = {"Buy": 8.0, "Hold": 3.0, "Sell": -6.0}
CONFIDENCE_SCALE = {"High": 1.0, "Medium": 0.75, "Low": 0.5}

_INCOME_GOAL = re.compile(r"income|retire|pension|dividend|yield", re.I)
_LEGACY_GOAL = re.compile(r"legacy|estate|inherit|heirs|grandchild|philanthrop", re.I)
_INCOME_PRODUCT = re.compile(r"income|dividend|yield|bond|credit|reit|deposit|money market|bill", re.I)

Objective = str  # "income" | "preservation" | "growth" | "legacy" | "balanced"


def derive_objective(p: ClientProfile, a: ProfileAssessment) -> Objective:
    """The client's main objective, from stated goals first, then risk level."""
    goal_text = " ".join(
        [g.goal for g in (p.financial_goals or [])]
        + list(p.short_term_goals or []) + list(p.medium_term_goals or []) + list(p.long_term_goals or [])
    )
    level = a.effective_level
    if _INCOME_GOAL.search(goal_text):
        return "income"
    if level is not None and level <= 2:
        return "preservation"
    if _LEGACY_GOAL.search(goal_text):
        return "legacy"
    if level is not None and level >= 4:
        return "growth"
    return "balanced"


@dataclass
class Ranked:
    sp: ScreenedProduct
    total: float
    components: dict[str, float]


def _objective_fit(sp: ScreenedProduct, objective: Objective) -> float:
    prod = sp.product
    text = f"{prod.product_name} {prod.sub_asset_class or ''} {prod.product_type or ''}"
    income_yield = prod.distribution_yield if prod.distribution_yield is not None else prod.yield_to_maturity
    growth = GROWTH_WEIGHT.get(sp.asset_class, 0.0)
    if objective == "income":
        if income_yield is not None:
            return round(min(10.0, income_yield * 2), 2)
        return 4.0 if _INCOME_PRODUCT.search(text) else 0.0
    if objective == "preservation":
        return {1: 10.0, 2: 7.0, 3: 3.0}.get(prod.risk_rating, 0.0)
    if objective == "growth":
        return 10.0 if growth else (4.0 if sp.asset_class in (AssetClass.REAL_ESTATE, AssetClass.GOLD) else 1.0)
    if objective == "legacy":
        horizon = prod.recommended_horizon or 0
        return round(min(10.0, horizon * 1.2 + (3.0 if growth else 0.0)), 2)
    # balanced: core building blocks first
    return {AssetClass.FIXED_INCOME: 7.0, AssetClass.EQUITIES: 7.0}.get(sp.asset_class, 4.0)


def _house_view(sp: ScreenedProduct, hv: HouseView) -> float:
    v = hv.for_class(sp.asset_class.value)
    if v is None:
        return 0.0
    return round(HOUSE_VIEW_POINTS[v.view] * CONFIDENCE_SCALE[v.confidence], 2)


def _risk_budget_use(sp: ScreenedProduct, level: Optional[int]) -> float:
    if not level or sp.product.risk_rating is None:
        return 0.0
    weight = 4.0 if level >= 4 else 2.0
    return round(weight * min(sp.product.risk_rating, level) / level, 2)


def _horizon_match(sp: ScreenedProduct, horizon: Optional[float]) -> float:
    rec = sp.product.recommended_horizon
    if rec is None or horizon is None:
        return 1.5
    return round(max(0.0, 3.0 - max(0.0, rec - horizon)), 2)


def _currency_fit(sp: ScreenedProduct, base_currency: Optional[str]) -> float:
    if not base_currency:
        return 1.0
    return 0.0 if sp.is_foreign_unhedged(base_currency) else 2.0


def _data_quality(sp: ScreenedProduct) -> float:
    prod = sp.product
    s = {"COMPLETE": 2.0, "PARTIAL": 0.0}.get(prod.data_completeness, -1.0)
    if prod.volatility is None or prod.maximum_drawdown is None:
        s -= 3.0
    return max(-3.0, s)


def _rating(sp: ScreenedProduct) -> float:
    rating = getattr(sp.product, "rating", None)
    return 1.0 if rating is None else round(rating / 5 * 2, 2)


def score(sp: ScreenedProduct, objective: Objective, hv: HouseView, level: Optional[int],
          horizon: Optional[float], base_currency: Optional[str]) -> Ranked:
    components = {
        "objective_fit": _objective_fit(sp, objective),
        "house_view": _house_view(sp, hv),
        "risk_budget_use": _risk_budget_use(sp, level),
        "horizon_match": _horizon_match(sp, horizon),
        "currency_fit": _currency_fit(sp, base_currency),
        "data_quality": _data_quality(sp),
        "rating": _rating(sp),
    }
    return Ranked(sp=sp, total=round(sum(components.values()), 2), components=components)


def rank(eligible: list[ScreenedProduct], objective: Objective, hv: HouseView, level: Optional[int],
         horizon: Optional[float], base_currency: Optional[str]) -> list[Ranked]:
    ranked = [score(sp, objective, hv, level, horizon, base_currency) for sp in eligible]
    return sorted(ranked, key=lambda r: (-r.total, r.sp.product_id))


def shortlist(ranked: list[Ranked], top_n: int, max_per_asset_class: int) -> tuple[list[Ranked], list[Ranked]]:
    """Take the best products in order, at most `max_per_asset_class` from one class."""
    picked: list[Ranked] = []
    rest: list[Ranked] = []
    per_class: dict[AssetClass, int] = {}
    for r in ranked:
        ac = r.sp.asset_class
        if len(picked) < top_n and per_class.get(ac, 0) < max_per_asset_class:
            picked.append(r)
            per_class[ac] = per_class.get(ac, 0) + 1
        else:
            rest.append(r)
    return picked, rest
