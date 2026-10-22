"""
Portfolio construction: turns the six SAA templates (A capital
preservation through F opportunistic - the same templates the PM SAA
builder offers) into concrete, constraint-respecting product allocations.

This is a rules-based heuristic, NOT a mathematical optimiser - the
response never claims optimality. The pipeline for each option:

  1. Suitability gates   - each template has a minimum risk level and
                            horizon; e.g. E/F are not offered to a cautious
                            client or one with a short or unknown horizon.
  2. Availability        - template asset classes with no eligible
                            products have their weight reassigned.
  3. Growth ceiling      - growth-asset share capped by effective risk
                            level and horizon.
  4. Iterate until stable (bounded):
       allocate each asset-class sleeve to ranked products, respecting the
       per-product concentration cap and minimum investment sizes;
       redistribute any unallocatable weight (defensive classes first);
       de-risk if the estimated stress drawdown breaches the client's limit;
       swap out foreign-currency products if FX exposure breaches the limit.
  5. If a constraint still can't be met, the option is returned INFEASIBLE
     with the reason - never silently in breach.
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from app.agents.portfolio_agent.engine.product_screening import ScreenedProduct, ScreeningResult, rank_products
from app.agents.portfolio_agent.taxonomy import (
    ASSET_CLASS_ORDER,
    DEFENSIVE_CLASSES,
    GROWTH_CEILING_BY_RISK_LEVEL,
    GROWTH_WEIGHT,
    AssetClass,
)

EPS = 1e-6
MAX_ITERATIONS = 15
# Split a sleeve across at least two products once it reaches this weight
# (when two are available), for diversification within the asset class.
DIVERSIFY_SLEEVE_AT_PCT = 20.0
# Aim a little under the drawdown limit when de-risking, so re-selecting
# products after a weight change doesn't land fractionally above it.
DRAWDOWN_HEADROOM = 0.98
# Options are near-duplicates when less than this share of the portfolio
# (half the sum of absolute asset-class weight differences) would differ.
MIN_DIFFERENTIATION_PP = 10.0
# A template whose growth-asset share has to be cut by more than this (pp)
# to fit the client's limits no longer is that template, so it is withdrawn
# rather than offered under its name (e.g. a "Growth" option at 28% growth).
MAX_GROWTH_ADAPTATION_PP = 10.0
# Horizon caps on growth assets (on top of the risk-level ceiling).
SHORT_HORIZON_YEARS, SHORT_HORIZON_CAP = 3.0, 15.0
MEDIUM_HORIZON_YEARS, MEDIUM_HORIZON_CAP = 5.0, 30.0


@dataclass(frozen=True)
class OptionTemplate:
    option_id: str
    name: str
    objective: str
    weights: dict
    defensiveness: float  # 0-1, used in product ranking
    min_risk_level: int  # lowest effective risk level it is offered to
    min_horizon_years: float  # shortest goal horizon it is offered for


def _split(*pcts: float) -> dict:
    """Template weights in the SAA builder's class order."""
    return {ac: float(p) for ac, p in zip(ASSET_CLASS_ORDER, pcts) if p}


# Splits are the SAA builder's templates A-F (Cash, Fixed income, Equities,
# Hedge funds, Private markets, Real estate, Gold).
TEMPLATES = (
    OptionTemplate("A", "Capital preservation", "Preserve capital and liquidity; accept low returns for stability.",
                   _split(30, 40, 10, 5, 0, 5, 10), 1.0, 1, 0.0),
    OptionTemplate("B", "Income", "Generate steady income with limited volatility.",
                   _split(20, 45, 15, 5, 0, 8, 7), 0.8, 1, 0.0),
    OptionTemplate("C", "Balanced", "Balance income and capital growth with moderate risk.",
                   _split(15, 35, 30, 5, 3, 5, 7), 0.5, 2, 3.0),
    OptionTemplate("D", "Growth", "Grow capital over the medium to long term, accepting market swings.",
                   _split(10, 25, 40, 7, 5, 6, 7), 0.3, 3, 5.0),
    OptionTemplate("E", "Aggressive growth", "Maximise long-term growth; expect large interim losses.",
                   _split(5, 15, 50, 8, 8, 6, 8), 0.1, 4, 7.0),
    OptionTemplate("F", "Opportunistic", "Pursue higher returns through equities and alternatives, including illiquid assets.",
                   _split(5, 10, 45, 12, 12, 8, 8), 0.0, 4, 7.0),
)


def template_growth(t: OptionTemplate) -> float:
    return growth_share(t.weights)


@dataclass
class ConstructionContext:
    eligible_value: float
    base_currency: str
    effective_level: int
    horizon_years: Optional[float]
    max_single_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    max_fx_pct: Optional[float]
    screening: ScreeningResult
    esg_preferred: bool = False
    exclusion_reasons: dict = field(default_factory=dict)  # AssetClass -> why no products
    # Points removed from the growth ceiling because of market conditions
    # (e.g. a recession call from the Market Researcher); 0 = no adjustment.
    market_growth_reduction: float = 0.0

    @property
    def growth_ceiling(self) -> float:
        ceiling = GROWTH_CEILING_BY_RISK_LEVEL[self.effective_level]
        if self.horizon_years is None or self.horizon_years < MEDIUM_HORIZON_YEARS:
            ceiling = min(ceiling, MEDIUM_HORIZON_CAP)
        if self.horizon_years is not None and self.horizon_years < SHORT_HORIZON_YEARS:
            ceiling = min(ceiling, SHORT_HORIZON_CAP)
        return max(0.0, ceiling - self.market_growth_reduction)

    def available_classes(self) -> set:
        return {ac for ac, lst in self.screening.by_class.items() if lst}


@dataclass
class Position:
    sp: ScreenedProduct
    pct: float
    amount: float = 0.0


@dataclass
class BuiltOption:
    template: OptionTemplate
    status: str  # SUITABLE | SUITABLE_WITH_MODIFICATIONS | NOT_SUITABLE | INFEASIBLE
    explanation: str
    modifications: list[str] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    growth_ceiling: Optional[float] = None

    @property
    def is_offered(self) -> bool:
        return self.status in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS")

    def class_weights(self) -> dict:
        out: dict = {}
        for pos in self.positions:
            out[pos.sp.asset_class] = out.get(pos.sp.asset_class, 0.0) + pos.pct
        return out

    def growth_share(self) -> float:
        return growth_share(self.class_weights())


def _weights_of(positions: list) -> dict:
    out: dict = {}
    for p in positions:
        out[p.sp.asset_class] = out.get(p.sp.asset_class, 0.0) + p.pct
    return out


def growth_share(weights: dict) -> float:
    return sum(w * GROWTH_WEIGHT[ac] for ac, w in weights.items())


def _not_offered(t: OptionTemplate, status: str, why: str, mods=None) -> BuiltOption:
    return BuiltOption(template=t, status=status, explanation=why, modifications=list(mods or []))


# --- Public entry points -----------------------------------------------------

def build_option(t: OptionTemplate, ctx: ConstructionContext) -> BuiltOption:
    if ctx.effective_level < t.min_risk_level:
        return _not_offered(t, "NOT_SUITABLE", (
            f"The client's effective risk level is {ctx.effective_level} of 5; the {t.name} template needs at "
            f"least level {t.min_risk_level}."
        ))
    if t.min_horizon_years > 0 and ctx.horizon_years is None:
        return _not_offered(t, "NOT_SUITABLE", (
            f"The client's investment horizon is not confirmed, so the {t.name} template (needs at least "
            f"{t.min_horizon_years:g} years) cannot be justified."
        ))
    if ctx.horizon_years is not None and ctx.horizon_years < t.min_horizon_years:
        return _not_offered(t, "NOT_SUITABLE", (
            f"The shortest goal horizon is {ctx.horizon_years:g} years; the {t.name} template needs at least "
            f"{t.min_horizon_years:g} years to recover from the drawdowns it can suffer."
        ))

    mods: list[str] = []
    weights = {ac: w for ac, w in t.weights.items() if w > 0}

    weights, err = _reassign_unavailable(weights, ctx, mods)
    if err:
        return _not_offered(t, "INFEASIBLE", err, mods)

    ceiling = ctx.growth_ceiling
    if growth_share(weights) > ceiling + EPS:
        before = growth_share(weights)
        weights = _shift_growth_to_defensive(weights, ceiling, ctx)
        if weights is None:
            return _not_offered(t, "INFEASIBLE", "No eligible defensive products to absorb the growth-ceiling reduction.", mods)
        mods.append(
            f"Growth assets reduced from {before:.0f}% to {growth_share(weights):.0f}% to stay within the "
            f"{ceiling:.0f}% ceiling for the client's effective risk level and horizon."
        )

    avoid: set[str] = set()
    derisked = False
    for _ in range(MAX_ITERATIONS):
        positions, leftover = _allocate(weights, ctx, t, avoid)
        if sum(leftover.values()) > EPS:
            weights, err = _redistribute(weights, leftover, ctx, t, avoid, mods)
            if err:
                return _not_offered(t, "INFEASIBLE", err, mods)
            continue

        stress = stress_drawdown(positions)
        if ctx.max_drawdown_pct is not None and stress is not None and stress > ctx.max_drawdown_pct + EPS:
            new_weights = _de_risk(weights, positions, ctx)
            if new_weights is None:
                return _not_offered(t, "INFEASIBLE", (
                    f"Even the most defensive mix of eligible products has an estimated stress drawdown of "
                    f"{stress:.1f}%, above the client's {ctx.max_drawdown_pct:g}% limit."
                ), mods)
            if not derisked:
                mods.append(
                    f"Allocation de-risked so the estimated stress drawdown stays within the client's "
                    f"{ctx.max_drawdown_pct:g}% maximum acceptable drawdown."
                )
                derisked = True
            weights = new_weights
            continue

        fx = foreign_currency_exposure(positions, ctx.base_currency)
        if ctx.max_fx_pct is not None and fx > ctx.max_fx_pct + EPS:
            foreign = sorted(
                (p for p in positions if p.sp.is_foreign_unhedged(ctx.base_currency)), key=lambda p: -p.pct
            )
            avoid.add(foreign[0].sp.product_id)
            mods.append(
                f"{foreign[0].sp.product.product_name} replaced to keep unhedged foreign-currency exposure within "
                f"{ctx.max_fx_pct:g}%."
            )
            continue
        break
    else:
        return _not_offered(t, "INFEASIBLE", "Constraints could not all be satisfied simultaneously.", mods)

    positions = finalise(positions, ctx.eligible_value)
    built_growth = growth_share(_weights_of(positions))
    cut = template_growth(t) - built_growth
    if cut > MAX_GROWTH_ADAPTATION_PP:
        return _not_offered(t, "NOT_SUITABLE", (
            f"To fit the client's limits, the {t.name} template's growth assets would fall from "
            f"{template_growth(t):.0f}% to {built_growth:.1f}%; it would no longer be a {t.name} portfolio, so it is "
            "not offered. " + " ".join(mods)
        ).strip(), mods)
    status = "SUITABLE_WITH_MODIFICATIONS" if mods else "SUITABLE"
    explanation = (
        "Constructed from the standard template within all stated constraints."
        if not mods else "Template adapted to the client's circumstances: " + " ".join(mods)
    )
    return BuiltOption(t, status, explanation, mods, positions, ceiling)


def allocation_distance(a: BuiltOption, b: BuiltOption) -> float:
    """Share of the portfolio (pp) that differs between two options' asset-class mixes."""
    wa, wb = a.class_weights(), b.class_weights()
    return sum(abs(wa.get(ac, 0.0) - wb.get(ac, 0.0)) for ac in set(wa) | set(wb)) / 2


def differentiate(options: list[BuiltOption]) -> None:
    """Withdraw options that, after adaptation, are not materially different
    from the last offered, more conservative option - rather than present
    near-duplicates as genuine alternatives. Options are in A-F order."""
    last: BuiltOption | None = None
    for opt in options:
        if not opt.is_offered:
            continue
        if last is not None:
            distance = allocation_distance(opt, last)
            if distance < MIN_DIFFERENTIATION_PP:
                opt.status = "NOT_SUITABLE"
                opt.explanation = (
                    f"After applying the client's constraints, Option {opt.template.option_id}'s asset mix differs "
                    f"from Option {last.template.option_id}'s by only {distance:.1f}% of the portfolio "
                    f"({opt.growth_share():.1f}% vs {last.growth_share():.1f}% growth assets); it is not a materially "
                    "different alternative and is therefore not offered. " + " ".join(opt.modifications)
                ).strip()
                opt.positions = []
                continue
        last = opt


# --- Weight manipulation -----------------------------------------------------

def _available_defensive(ctx: ConstructionContext) -> list:
    avail = ctx.available_classes()
    return [ac for ac in DEFENSIVE_CLASSES if ac in avail]


def _spread(weights: dict, amount: float, recipients: list) -> dict:
    """Add `amount` to recipients in proportion to their current weights
    (equally if they currently hold nothing)."""
    out = dict(weights)
    base = sum(out.get(r, 0.0) for r in recipients)
    for r in recipients:
        share = (out.get(r, 0.0) / base) if base > EPS else 1 / len(recipients)
        out[r] = out.get(r, 0.0) + amount * share
    return out


def _reassign_unavailable(weights: dict, ctx: ConstructionContext, mods: list):
    avail = ctx.available_classes()
    missing = [ac for ac in weights if ac not in avail]
    if not missing:
        return weights, None
    out = {ac: w for ac, w in weights.items() if ac in avail}
    for ac in missing:
        amount = weights[ac]
        is_growth = GROWTH_WEIGHT[ac] > 0
        same_kind = [r for r in out if (GROWTH_WEIGHT[r] > 0) == is_growth]
        recipients = same_kind or _available_defensive(ctx)
        if not recipients:
            return out, f"No eligible products available to hold the {ac.value} allocation or a defensive substitute."
        out = _spread(out, amount, recipients)
        reason = ctx.exclusion_reasons.get(ac, "no eligible products")
        mods.append(
            f"{ac.value}: {reason}; its {amount:.0f}% was reassigned to {', '.join(r.value for r in recipients)}."
        )
    return out, None


def _shift_growth_to_defensive(weights: dict, ceiling: float, ctx: ConstructionContext) -> Optional[dict]:
    g = growth_share(weights)
    if g <= ceiling + EPS:
        return weights
    factor = ceiling / g
    out = {}
    freed = 0.0
    for ac, w in weights.items():
        if GROWTH_WEIGHT[ac] > 0:
            out[ac] = w * factor
            freed += w - out[ac]
        else:
            out[ac] = w
    recipients = [ac for ac in _available_defensive(ctx)]
    if not recipients:
        return None
    present = [r for r in recipients if out.get(r, 0) > EPS]
    return _spread(out, freed, present or recipients)


def _de_risk(weights: dict, positions: list, ctx: ConstructionContext) -> Optional[dict]:
    """Return new class weights whose estimated stress drawdown is within the
    limit (with headroom), or None if even an all-cash/defensive mix fails."""
    target = ctx.max_drawdown_pct * DRAWDOWN_HEADROOM
    dd = _class_drawdowns(positions)
    if dd is None:
        return None

    # Everything outside cash and fixed income is scaled down together - real
    # estate and gold are not "growth" in the SAA sense but still carry large
    # drawdowns, so de-risking must not move weight into them.
    growth = {ac: w for ac, w in weights.items() if ac not in DEFENSIVE_CLASSES and w > EPS}
    defensive = {ac: w for ac, w in weights.items() if ac in DEFENSIVE_CLASSES and w > EPS}
    if not defensive:
        recipients = _available_defensive(ctx)
        if not recipients:
            return None
        defensive = {recipients[0]: 0.0}
        dd.setdefault(recipients[0], _default_dd(recipients[0], ctx))

    wg = sum(growth.values())
    sg = sum(w * dd[ac] for ac, w in growth.items()) / 100
    sd = sum(w * dd.get(ac, 0.0) for ac, w in defensive.items()) / 100
    wd = sum(defensive.values())
    d_def = (sum(w * dd.get(ac, 0.0) for ac, w in defensive.items()) / wd) if wd > EPS else dd[next(iter(defensive))]

    if wg > EPS:
        denom = sg - wg * d_def / 100
        f = (target - sd - wg * d_def / 100) / denom if denom > EPS else 0.0
        f = max(0.0, min(f, 1.0 - 1e-3))
        out = {ac: w * f for ac, w in growth.items()}
        out.update(defensive)
        freed = wg * (1 - f)
        out = _spread(out, freed, list(defensive))
        if f > 0:
            return {ac: w for ac, w in out.items() if w > EPS}
        weights = {ac: w for ac, w in out.items() if w > EPS}

    # No growth left to cut: move the highest-drawdown defensive sleeves into cash.
    if AssetClass.CASH not in ctx.available_classes():
        return None
    out = dict(weights)
    dd.setdefault(AssetClass.CASH, _default_dd(AssetClass.CASH, ctx))
    current = sum(w * dd.get(ac, 0.0) for ac, w in out.items()) / 100
    for ac in sorted((a for a in out if a != AssetClass.CASH), key=lambda a: -dd.get(a, 0.0)):
        if current <= target + EPS:
            break
        excess = current - target
        per_pct = (dd.get(ac, 0.0) - dd[AssetClass.CASH]) / 100
        if per_pct <= EPS:
            continue
        move = min(out[ac], excess / per_pct)
        out[ac] -= move
        out[AssetClass.CASH] = out.get(AssetClass.CASH, 0.0) + move
        current -= move * per_pct
    if current > target + EPS:
        return None
    return {ac: w for ac, w in out.items() if w > EPS}


def _default_dd(ac, ctx: ConstructionContext) -> float:
    """Drawdown of the top-ranked product in a class not currently held."""
    for sp in ctx.screening.by_class.get(ac, []):
        if sp.product.maximum_drawdown is not None:
            return abs(sp.product.maximum_drawdown)
    return 0.0


def _class_drawdowns(positions: list) -> Optional[dict]:
    totals: dict = {}
    weights: dict = {}
    for p in positions:
        if p.sp.product.maximum_drawdown is None:
            return None
        ac = p.sp.asset_class
        totals[ac] = totals.get(ac, 0.0) + p.pct * abs(p.sp.product.maximum_drawdown)
        weights[ac] = weights.get(ac, 0.0) + p.pct
    return {ac: totals[ac] / weights[ac] for ac in totals if weights[ac] > EPS}


# --- Product allocation ------------------------------------------------------

def _ranked(ac, ctx: ConstructionContext, t: OptionTemplate, avoid: set) -> list[ScreenedProduct]:
    pool = [sp for sp in ctx.screening.by_class.get(ac, []) if sp.product_id not in avoid]
    return rank_products(pool, ctx.base_currency, t.defensiveness, ctx.esg_preferred, ctx.effective_level)


def allocate_sleeve(weight: float, pool: list[ScreenedProduct], cap: Optional[float], eligible_value: float):
    """Split one asset-class sleeve across ranked products.

    Uses the fewest products that respect the per-product cap (at least two
    for large sleeves, when available), skipping products whose minimum
    investment exceeds their share. Returns (positions, unallocated_pct).
    """
    cap = cap or 100.0
    desired = max(math.ceil(weight / cap - EPS), 2 if weight >= DIVERSIFY_SLEEVE_AT_PCT else 1)
    for k in range(min(desired, len(pool)), 0, -1):
        share = min(weight / k, cap)
        amount = eligible_value * share / 100
        affordable = [sp for sp in pool if (sp.product.minimum_investment or 0) <= amount + 0.005]
        if len(affordable) >= k:
            return [Position(sp, share) for sp in affordable[:k]], max(0.0, weight - share * k)
    return [], weight


def _allocate(weights: dict, ctx: ConstructionContext, t: OptionTemplate, avoid: set):
    positions: list[Position] = []
    leftover: dict = {}
    for ac, w in weights.items():
        if w <= EPS:
            continue
        got, rest = allocate_sleeve(w, _ranked(ac, ctx, t, avoid), ctx.max_single_pct, ctx.eligible_value)
        positions.extend(got)
        if rest > EPS:
            leftover[ac] = rest
    return positions, leftover


def _class_capacity(ac, ctx: ConstructionContext, t: OptionTemplate, avoid: set) -> float:
    n = len(_ranked(ac, ctx, t, avoid))
    return n * (ctx.max_single_pct or 100.0)


def _redistribute(weights: dict, leftover: dict, ctx, t, avoid, mods):
    out = dict(weights)
    total = 0.0
    for ac, rest in leftover.items():
        out[ac] -= rest
        total += rest
    blocked = set(leftover)

    recipients = [ac for ac in _available_defensive(ctx) if ac not in blocked]
    recipients += [ac for ac in out if ac not in blocked and ac not in recipients and out[ac] > EPS]
    ceiling = ctx.growth_ceiling
    for ac in recipients:
        if total <= EPS:
            break
        room = _class_capacity(ac, ctx, t, avoid) - out.get(ac, 0.0)
        if GROWTH_WEIGHT[ac] > 0:
            room = min(room, (ceiling - growth_share(out)) / GROWTH_WEIGHT[ac])
        take = min(total, max(0.0, room))
        if take > EPS:
            out[ac] = out.get(ac, 0.0) + take
            total -= take

    names = ", ".join(ac.value for ac in leftover)
    if total > EPS:
        cap_txt = f"{ctx.max_single_pct:g}% per-product limit" if ctx.max_single_pct else "available products"
        return out, (
            f"{total:.1f}% of the portfolio cannot be placed: the {cap_txt}, minimum investment sizes and the "
            f"eligible product shelf cannot absorb the full allocation (shortfall in {names})."
        )
    mods.append(
        f"Weight in {names} that could not be placed (per-product limit or minimum investment) was moved to "
        "other eligible sleeves."
    )
    return {ac: w for ac, w in out.items() if w > EPS}, None


# --- Portfolio-level measures used inside the construction loop --------------

def stress_drawdown(positions: list) -> Optional[float]:
    """Sum of weight x historical max drawdown: assumes every holding hits its
    worst historical drawdown at the same time (perfect correlation), so it
    is a deliberately conservative upper-bound estimate."""
    if any(p.sp.product.maximum_drawdown is None for p in positions):
        return None
    return sum(p.pct * abs(p.sp.product.maximum_drawdown) for p in positions) / 100


def foreign_currency_exposure(positions: list, base_currency: str) -> float:
    return sum(p.pct for p in positions if p.sp.is_foreign_unhedged(base_currency))


def finalise(positions: list, eligible_value: float) -> list[Position]:
    """Round to 2dp so percentages sum to exactly 100.00 and amounts to
    exactly the eligible value, absorbing rounding residue in the largest
    position."""
    positions = [p for p in positions if p.pct > EPS]
    positions.sort(key=lambda p: (-p.pct, p.sp.product_id))
    for p in positions:
        p.pct = round(p.pct, 2)
    residual = round(100.0 - sum(p.pct for p in positions), 2)
    positions[0].pct = round(positions[0].pct + residual, 2)

    for p in positions:
        p.amount = round(eligible_value * p.pct / 100, 2)
    residual_amt = round(round(eligible_value, 2) - sum(p.amount for p in positions), 2)
    positions[0].amount = round(positions[0].amount + residual_amt, 2)
    return positions
