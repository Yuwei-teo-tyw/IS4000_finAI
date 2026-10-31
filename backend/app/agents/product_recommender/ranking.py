"""
Ranks products that already passed the suitability gate, role by role.

roles.py plans which roles the shortlist fills. Here each product is scored
only against the other products that fill the same role, since a money
market fund and a private equity fund do different jobs and one scale for
both says little. Every component is a named number in [0, 1], weighted per
role (WEIGHTS, each role's weights sum to 10), so the PS can see why a
product ranked where it did.

The shortlist is then picked greedily, slot by slot. Each pick lowers the
score of the products still waiting that would overlap it (same sub-asset
class, same issuer, same currency and asset class), which replaces a fixed
cap per asset class. A slot that no product can fill passes to the best
remaining product in another role, if it scores at least
MIN_PASSED_ON_SCORE. Ties break by product_id, so the order is reproducible.

FORBIDDEN INPUTS: management_fee, transaction_fee, any other cost or
commission field. Fees are shown to the PS for information only and must
never move a product up or down this list.
"""
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Optional

from app.agents.portfolio_agent.engine.construction import TEMPLATES
from app.agents.portfolio_agent.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.taxonomy import AssetClass, parse_asset_class
from app.agents.product_recommender import roles as roles_mod
from app.agents.product_recommender.roles import ROLES, RoleSlot
from app.agents.product_recommender.suitability import ScreenedProduct

if TYPE_CHECKING:
    from app.agents.product_recommender.asset_views.builder import AgentStance

VIEW_POINTS = {"Buy": 1.0, "Hold": 0.5, "Sell": 0.0}
CONFIDENCE_SCALE = {"High": 1.0, "Medium": 0.75, "Low": 0.5}
LIQUIDITY_TIER = {"DAILY": 1.0, "WEEKLY": 0.7, "MONTHLY": 0.4, "QUARTERLY": 0.1, "AT_MATURITY": 0.1, "LOCKED": 0.0}

WEIGHTS: dict[str, dict[str, float]] = {
    "liquidity": {"role_fit": 4.0, "risk_adjusted": 0.5, "drawdown_fit": 0.5, "market_view": 1.0, "gap_fit": 0.5,
                  "horizon_match": 1.0, "currency_fit": 1.5, "data_quality": 0.75, "rating": 0.25},
    "income": {"role_fit": 3.5, "risk_adjusted": 1.5, "drawdown_fit": 1.0, "market_view": 1.5, "gap_fit": 0.75,
               "horizon_match": 0.5, "currency_fit": 0.5, "data_quality": 0.5, "rating": 0.25},
    "stability": {"role_fit": 3.5, "risk_adjusted": 1.0, "drawdown_fit": 1.5, "market_view": 1.0, "gap_fit": 1.0,
                  "horizon_match": 0.75, "currency_fit": 0.5, "data_quality": 0.5, "rating": 0.25},
    "core_growth": {"role_fit": 2.5, "risk_adjusted": 2.0, "drawdown_fit": 0.75, "market_view": 2.0, "gap_fit": 1.0,
                    "horizon_match": 0.75, "currency_fit": 0.5, "data_quality": 0.25, "rating": 0.25},
    "diversifier": {"role_fit": 3.0, "risk_adjusted": 1.5, "drawdown_fit": 1.0, "market_view": 1.5, "gap_fit": 1.0,
                    "horizon_match": 1.0, "currency_fit": 0.5, "data_quality": 0.25, "rating": 0.25},
}
# Points taken off a waiting product for each already-picked product it overlaps.
OVERLAP_PENALTY = {"sub_asset_class": 2.0, "issuer": 1.0, "currency_and_class": 0.5}
# The smallest gap, in each raw reading's own unit, that counts as the full 0-1 range within a role.
MIN_SPREAD = {
    "liquidity": 5.0,      # dealing tier x 10 minus volatility (%)
    "income": 0.5,         # yield per unit of volatility
    "stability": 5.0,      # drawdown (%) plus half the duration (years)
    "core_growth": 5.0,    # annualised return (%)
    "diversifier": 10.0,   # drawdown (%)
    "risk_adjusted": 0.5,  # Sharpe ratio
}
# A slot passed on from a role with no eligible product is filled only by a product scoring at least this
# (of 10, after the overlap penalty), so a thin shelf gives a shorter shortlist, not near-duplicates.
MIN_PASSED_ON_SCORE = 4.0
# Reference mix per risk level, for gap_fit: the Portfolio Agent's SAA templates A-E.
REFERENCE_MIX = {1: TEMPLATES[0].weights, 2: TEMPLATES[1].weights, 3: TEMPLATES[2].weights,
                 4: TEMPLATES[3].weights, 5: TEMPLATES[4].weights}
# A gap of this many percentage points to the reference mix moves gap_fit from 0.5 to 1 (or 0).
GAP_FULL_SCALE_PP = 20.0

_INCOME_GOAL = re.compile(r"income|retire|pension|dividend|yield", re.I)
_LEGACY_GOAL = re.compile(r"legacy|estate|inherit|heirs|grandchild|philanthrop", re.I)

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
class RankContext:
    level: Optional[int]
    horizon: Optional[float]
    base_currency: Optional[str]
    max_drawdown: Optional[float]
    views: dict  # AssetClass -> AgentStance
    current_mix: Optional[dict[AssetClass, float]]  # % per class, None when the client's holdings are unknown

    @property
    def reference_mix(self) -> dict[AssetClass, float]:
        return REFERENCE_MIX.get(self.level or roles_mod.DEFAULT_LEVEL, REFERENCE_MIX[roles_mod.DEFAULT_LEVEL])


@dataclass
class Ranked:
    sp: ScreenedProduct
    role: str
    total: float
    components: dict[str, float]
    notes: list[str] = field(default_factory=list)
    role_rank: int = 0
    passed_from: Optional[str] = None  # the role whose unfilled slot this pick took


def current_mix(p: ClientProfile) -> Optional[dict[AssetClass, float]]:
    """The client's current allocation as % per asset class, from current_asset_allocation or current_holdings."""
    if p.current_asset_allocation:
        out: dict[AssetClass, float] = {}
        for label, pct in p.current_asset_allocation.items():
            if (ac := parse_asset_class(label)) is not None:
                out[ac] = out.get(ac, 0.0) + pct
        return out or None
    holdings = [h for h in (p.current_holdings or []) if parse_asset_class(h.asset_class or "") is not None]
    total = sum(h.market_value for h in holdings)
    if not total:
        return None
    out = {}
    for h in holdings:
        ac = parse_asset_class(h.asset_class)
        out[ac] = out.get(ac, 0.0) + 100 * h.market_value / total
    return out


# --- Raw readings (higher is better within a role; None = no data) ----------

def _returns(sp: ScreenedProduct) -> Optional[float]:
    r = sp.product.historical_returns or {}
    return next((r[k] for k in ("5y", "3y", "1y") if r.get(k) is not None), None)


def _role_fit_raw(sp: ScreenedProduct, role: str) -> Optional[float]:
    p = sp.product
    if role == "liquidity":
        tier = LIQUIDITY_TIER.get(p.liquidity or "", 0.0)
        return tier * 10 - (p.volatility if p.volatility is not None else 10.0)
    if role == "income":
        y = roles_mod.yield_of(sp)
        return None if y is None else y / max(p.volatility or 5.0, 1.0)
    if role == "stability":
        if p.maximum_drawdown is None:
            return None
        return -abs(p.maximum_drawdown) - 0.5 * (p.duration or 0.0)
    if role == "core_growth":
        return _returns(sp)
    return None if p.maximum_drawdown is None else -abs(p.maximum_drawdown)  # diversifier: holds up in a sell-off


def _risk_adjusted_raw(sp: ScreenedProduct) -> Optional[float]:
    p = sp.product
    sharpe = getattr(p, "sharpe_ratio", None)  # a ShelfProduct field; the PM's ProductCandidate has none
    if sharpe is not None:
        return sharpe
    ret = _returns(sp)
    if ret is not None and p.volatility:
        return ret / p.volatility
    return None


def _normalise(raw: dict[str, Optional[float]], min_spread: float) -> dict[str, float]:
    """1 for the best in the role, less by how far behind it a product is, over the role's spread but at least
    `min_spread`, so a tiny gap between two funds is not stretched to the whole 0-1 range. Missing data scores 0."""
    vals = [v for v in raw.values() if v is not None]
    if not vals:
        return {pid: 0.0 for pid in raw}
    hi, spread = max(vals), max(max(vals) - min(vals), min_spread)
    return {pid: 0.0 if v is None else _clip(1 - (hi - v) / spread) for pid, v in raw.items()}


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _market_view(sp: ScreenedProduct, ctx: RankContext) -> tuple[float, Optional[str]]:
    st: Optional[AgentStance] = ctx.views.get(sp.asset_class)
    if st is None:
        return 0.5, None
    value = 0.5 + (VIEW_POINTS[st.view] - 0.5) * CONFIDENCE_SCALE[st.confidence]
    note = None
    if st.adjustment != "unchanged":
        note = (f"Agent view on {sp.asset_class.value.lower()} is {st.view} ({st.confidence.lower()} confidence): "
                f"the CIO's {st.cio.cio_term} ({st.cio.view}), {st.adjustment} on current market data.")
    return value, note


def _drawdown_fit(sp: ScreenedProduct, limit: Optional[float]) -> float:
    mdd = sp.product.maximum_drawdown
    if mdd is None:
        return 0.0
    if not limit:
        return 0.5
    return _clip(1.5 - abs(mdd) / limit)


def _gap_fit(sp: ScreenedProduct, ctx: RankContext) -> float:
    if ctx.current_mix is None:
        return 0.5
    gap = ctx.reference_mix.get(sp.asset_class, 0.0) - ctx.current_mix.get(sp.asset_class, 0.0)
    return _clip(0.5 + gap / (2 * GAP_FULL_SCALE_PP))


def _horizon_match(sp: ScreenedProduct, horizon: Optional[float]) -> float:
    rec = sp.product.recommended_horizon
    if rec is None or horizon is None:
        return 0.5
    return _clip((3.0 - max(0.0, rec - horizon)) / 3.0)


def _currency_fit(sp: ScreenedProduct, base_currency: Optional[str]) -> float:
    if not base_currency:
        return 0.5
    return 0.0 if sp.is_foreign_unhedged(base_currency) else 1.0


def _data_quality(sp: ScreenedProduct) -> float:
    prod = sp.product
    s = {"COMPLETE": 2.0, "PARTIAL": 0.0}.get(prod.data_completeness, -1.0)
    if prod.volatility is None or prod.maximum_drawdown is None:
        s -= 3.0
    return (max(-3.0, s) + 3.0) / 5.0


def _rating(sp: ScreenedProduct) -> float:
    rating = getattr(sp.product, "rating", None)
    return 0.5 if rating is None else rating / 5


def score_role(role: str, candidates: list[ScreenedProduct], ctx: RankContext) -> list[Ranked]:
    """Every candidate for one role, scored against the others in that role, best first."""
    fit = _normalise({sp.product_id: _role_fit_raw(sp, role) for sp in candidates}, MIN_SPREAD[role])
    risk = _normalise({sp.product_id: _risk_adjusted_raw(sp) for sp in candidates}, MIN_SPREAD["risk_adjusted"])
    w = WEIGHTS[role]
    out = []
    for sp in candidates:
        view, view_note = _market_view(sp, ctx)
        parts = {
            "role_fit": fit[sp.product_id],
            "risk_adjusted": risk[sp.product_id],
            "drawdown_fit": _drawdown_fit(sp, ctx.max_drawdown),
            "market_view": view,
            "gap_fit": _gap_fit(sp, ctx),
            "horizon_match": _horizon_match(sp, ctx.horizon),
            "currency_fit": _currency_fit(sp, ctx.base_currency),
            "data_quality": _data_quality(sp),
            "rating": _rating(sp),
        }
        components = {k: round(w[k] * v, 2) for k, v in parts.items()}
        notes = [view_note] if view_note else []
        if _risk_adjusted_raw(sp) is None:
            notes.append("No Sharpe ratio or return history on file, so risk-adjusted quality scored 0.")
        out.append(Ranked(sp=sp, role=role, total=round(sum(components.values()), 2), components=components, notes=notes))
    return sorted(out, key=lambda r: (-r.total, r.sp.product_id))


def score_all(eligible: list[ScreenedProduct], ctx: RankContext) -> dict[str, list[Ranked]]:
    by_role: dict[str, list[ScreenedProduct]] = {r: [] for r in ROLES}
    for sp in eligible:
        for role in roles_mod.roles_for(sp):
            by_role[role].append(sp)
    return {role: score_role(role, cands, ctx) for role, cands in by_role.items()}


def overlap_penalty(sp: ScreenedProduct, picked: list[Ranked]) -> float:
    p = sp.product
    total = 0.0
    for r in picked:
        q = r.sp.product
        if p.sub_asset_class and q.sub_asset_class and p.sub_asset_class.lower() == q.sub_asset_class.lower():
            total += OVERLAP_PENALTY["sub_asset_class"]
        if p.issuer and q.issuer and p.issuer.lower() == q.issuer.lower():
            total += OVERLAP_PENALTY["issuer"]
        if p.currency == q.currency and sp.asset_class == r.sp.asset_class:
            total += OVERLAP_PENALTY["currency_and_class"]
    return total


@dataclass
class Selection:
    picked: list[Ranked]
    filled: dict[str, int]
    passed: dict[str, int]  # role -> slots it could not fill and passed on
    rest: list[Ranked]  # eligible but not picked, each under its best role


def select(plan: list[RoleSlot], scored: dict[str, list[Ranked]],
           max_per_asset_class: Optional[int] = None) -> Selection:
    picked: list[Ranked] = []
    taken: set[str] = set()
    per_class: dict[AssetClass, int] = {}
    filled = {s.role: 0 for s in plan}
    passed: dict[str, int] = {}

    def best(role: str) -> Optional[Ranked]:
        options = []
        for r in scored.get(role, []):
            if r.sp.product_id in taken:
                continue
            if max_per_asset_class is not None and per_class.get(r.sp.asset_class, 0) >= max_per_asset_class:
                continue
            pen = overlap_penalty(r.sp, picked)
            options.append((round(r.total - pen, 2), pen, r))
        if not options:
            return None
        total, pen, r = min(options, key=lambda o: (-o[0], o[2].sp.product_id))
        components = {**r.components, "overlap_penalty": -round(pen, 2)} if pen else dict(r.components)
        return replace(r, total=total, components=components)

    def take(r: Ranked, passed_from: Optional[str] = None) -> None:
        filled[r.role] = filled.get(r.role, 0) + 1
        picked.append(replace(r, role_rank=filled[r.role], passed_from=passed_from))
        taken.add(r.sp.product_id)
        per_class[r.sp.asset_class] = per_class.get(r.sp.asset_class, 0) + 1

    owed: list[str] = []
    for slot in plan:
        for _ in range(slot.slots):
            r = best(slot.role)
            if r is None:
                owed.append(slot.role)
                passed[slot.role] = passed.get(slot.role, 0) + 1
            else:
                take(r)
    # An unfilled slot goes to the best remaining product in the planned roles, else in any other role.
    planned = [s.role for s in plan]
    others = [r for r in ROLES if r not in planned]
    while owed:
        r = None
        for group in (planned, others):
            options = [x for x in (best(role) for role in group) if x is not None and x.total >= MIN_PASSED_ON_SCORE]
            if options:
                r = min(options, key=lambda x: (-x.total, x.sp.product_id))
                break
        if r is None:
            break
        take(r, passed_from=owed.pop(0))

    best_rest: dict[str, Ranked] = {}
    for role in ROLES:
        for r in scored.get(role, []):
            pid = r.sp.product_id
            if pid not in taken and (pid not in best_rest or r.total > best_rest[pid].total):
                best_rest[pid] = r
    rest = sorted(best_rest.values(), key=lambda r: (-r.total, r.sp.product_id))
    return Selection(picked=picked, filled=filled, passed=passed, rest=rest)
