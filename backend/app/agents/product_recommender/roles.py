"""
The roles a shortlist has to fill for one client, and which products can fill each.

Different asset classes serve different needs, so the shortlist is not "the
five highest scores, at most two per class". It is planned first: which
roles this client needs (a liquidity reserve, income, stability, core
growth, a diversifier) and how many of the `top_n` slots each gets. Products
are then ranked only against the other products that fill the same role
(see ranking.py).

The plan is deterministic and comes from the profile only:
  - a liquidity slot when a dated withdrawal falls inside the liquidity-need
    window, or the cash balance is below the minimum cash reserve;
  - the remaining slots split by the client's risk level (SLOT_WEIGHTS);
  - one extra weight for the role the objective points to;
  - no diversifier slot when the shortest horizon is under 3 years, since
    those products have long recommended horizons and lock-ins.
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.agents.portfolio_agent.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.taxonomy import RISK_LEVEL_LABELS, AssetClass
from app.agents.product_recommender.suitability import (
    ScreenedProduct,
    near_term_need_months,
)

ROLES = ("liquidity", "income", "stability", "core_growth", "diversifier")
ROLE_LABELS = {
    "liquidity": "liquidity reserve",
    "income": "income",
    "stability": "stability",
    "core_growth": "core growth",
    "diversifier": "diversifier",
}

# A product with at least this yield (distribution or to maturity, %) can fill the income role. Cash is left out:
# its yield is what a liquidity reserve earns, not an income allocation.
INCOME_YIELD_PCT = 4.0
DIVERSIFIER_MIN_HORIZON_YEARS = 3.0

# Matched against "sub_asset_class product_type product_name", first match wins.
_SUB_ROLES: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = tuple((re.compile(p, re.I), r) for p, r in (
    (r"money market|\bcash\b|deposit|treasury bill|\bbills?\b", ("liquidity",)),
    (r"short duration|short[- ]term bond|ultra[- ]short", ("liquidity", "stability")),
    (r"investment[- ]grade", ("stability", "income")),
    (r"government|global core bond|aggregate|treasur", ("stability",)),
    (r"high yield|emerging markets debt|asia and singapore bond|asian? bond|private credit|income", ("income",)),
    (r"dividend", ("income", "core_growth")),
    (r"listed real estate|reit", ("income", "diversifier")),
    (r"absolute return", ("stability", "diversifier")),
    (r"private real estate|infrastructure|private equity|multi-strategy|long/short|hedge|gold|precious", ("diversifier",)),
))
_CLASS_ROLES = {
    AssetClass.CASH: ("liquidity",),
    AssetClass.FIXED_INCOME: ("stability",),
    AssetClass.EQUITIES: ("core_growth",),
    AssetClass.REAL_ESTATE: ("income", "diversifier"),
    AssetClass.GOLD: ("diversifier",),
    AssetClass.HEDGE_FUNDS: ("diversifier",),
    AssetClass.PRIVATE_MARKETS: ("diversifier",),
}

# Relative weight of each role in the slots left after any liquidity slot, by effective risk level.
SLOT_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"stability": 3, "income": 2},
    2: {"stability": 2, "income": 2, "core_growth": 1},
    3: {"stability": 1, "income": 1, "core_growth": 2, "diversifier": 1},
    4: {"stability": 0.5, "income": 1, "core_growth": 2.5, "diversifier": 1},
    5: {"income": 0.5, "core_growth": 3, "diversifier": 1.5},
}
DEFAULT_LEVEL = 3
OBJECTIVE_ROLE = {"income": "income", "preservation": "stability", "growth": "core_growth", "legacy": "diversifier"}


def yield_of(sp: ScreenedProduct) -> Optional[float]:
    p = sp.product
    return p.distribution_yield if p.distribution_yield is not None else p.yield_to_maturity


def roles_for(sp: ScreenedProduct) -> tuple[str, ...]:
    """Every role this product can fill, in ROLES order."""
    p = sp.product
    text = f"{p.sub_asset_class or ''} {p.product_type or ''} {p.product_name}"
    found: set[str] = set()
    for pattern, roles in _SUB_ROLES:
        if pattern.search(text):
            found.update(roles)
            break
    else:
        found.update(_CLASS_ROLES[sp.asset_class])
    if sp.asset_class == AssetClass.EQUITIES:
        found.add("core_growth")
    if sp.asset_class == AssetClass.FIXED_INCOME and "liquidity" in found:
        found.add("stability")  # a bill or short bond fund is still a bond holding
    y = yield_of(sp)
    if sp.asset_class != AssetClass.CASH and y is not None and y >= INCOME_YIELD_PCT:
        found.add("income")
    return tuple(r for r in ROLES if r in found)


@dataclass
class RoleSlot:
    role: str
    slots: int
    why: str


def _apportion(weights: dict[str, float], n: int) -> dict[str, int]:
    """Largest-remainder split of n slots by weight; ties go to the earlier role in ROLES."""
    total = sum(weights.values())
    if n <= 0 or total <= 0:
        return {}
    exact = {r: n * w / total for r, w in weights.items()}
    out = {r: int(x) for r, x in exact.items()}
    left = n - sum(out.values())
    for r in sorted(exact, key=lambda r: (-(exact[r] - out[r]), ROLES.index(r)))[:left]:
        out[r] += 1
    return {r: k for r, k in out.items() if k}


def liquidity_reason(p: ClientProfile, reference_date: date, window_months: int) -> Optional[str]:
    months = near_term_need_months(p, reference_date, window_months)
    if months is not None:
        return f"a dated withdrawal falls within {months:g} months"
    if p.minimum_cash_reserve and p.cash_balance is not None and p.cash_balance < p.minimum_cash_reserve:
        return "the cash balance is below the client's minimum cash reserve"
    return None


def plan_roles(p: ClientProfile, a: ProfileAssessment, objective: str, top_n: int, window_months: int) -> list[RoleSlot]:
    level = a.effective_level or DEFAULT_LEVEL
    plan: list[RoleSlot] = []
    liquid = liquidity_reason(p, a.reference_date, window_months)
    if liquid:
        plan.append(RoleSlot("liquidity", 1, f"{liquid}, so the shortlist holds a liquidity reserve"))

    weights = dict(SLOT_WEIGHTS[level])
    tilt = OBJECTIVE_ROLE.get(objective)
    if tilt:
        weights[tilt] = weights.get(tilt, 0) + 1
    short = a.shortest_horizon_years is not None and a.shortest_horizon_years < DIVERSIFIER_MIN_HORIZON_YEARS
    if short:
        weights.pop("diversifier", None)

    remaining = top_n - len(plan)
    split = _apportion(weights, remaining)
    label = RISK_LEVEL_LABELS.get(a.effective_level) if a.effective_level else "unknown, so balanced"
    for role in ROLES:
        k = split.get(role)
        if not k:
            continue
        why = f"risk level {a.effective_level or 'unknown'} ({label}) gives {ROLE_LABELS[role]} {k} of {remaining} slots"
        if role == tilt:
            why += f", with extra weight for the {objective} objective"
        plan.append(RoleSlot(role, k, why))
    return plan
