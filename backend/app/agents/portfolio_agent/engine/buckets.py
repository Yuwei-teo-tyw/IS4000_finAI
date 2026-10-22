"""
3L buckets (Liquidity, Longevity, Legacy): how a bucket's purpose and horizon
shape its SAA.

The 3L allocation decides how much of the client's wealth goes to each
bucket; this module decides how one bucket's amount is invested:

  - Liquidity holds the cash reserve and money due within a few years. It
    uses its own templates (cash and short-dated bonds only) and only
    products the client can get back within the bucket's horizon. Growth
    templates are never considered: money needed soon should not depend on
    markets recovering.
  - Longevity and Legacy use the six SAA templates (A-F), constrained by
    their own horizon and risk level. Neither is assumed to be riskier than
    the other: a Legacy bucket with a near transfer date or a cautious
    client gets cautious options.

The whole-client profile still applies to every bucket: risk capacity caps
any bucket risk level, and the client's drawdown, currency and concentration
limits apply inside each bucket.
"""
from dataclasses import dataclass, field, replace
from typing import Optional

from app.agents.portfolio_agent.engine.construction import TEMPLATES, OptionTemplate, _split
from app.agents.portfolio_agent.engine.liquidity import LiquidityResult
from app.agents.portfolio_agent.engine.product_screening import ScreeningResult
from app.agents.portfolio_agent.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_agent.schemas.client import BucketContext
from app.agents.portfolio_agent.schemas.response import Conflict, LiquidityPlan, MissingInformation, Statement
from app.agents.portfolio_agent.taxonomy import RISK_LEVEL_LABELS, AssetClass

LABELS = {"liquidity": "Liquidity", "longevity": "Longevity", "legacy": "Legacy"}
DEFAULT_OBJECTIVES = {
    "liquidity": "Meet short-term cash needs, emergency reserves and upcoming expenses; preserve capital and access.",
    "longevity": "Support medium- to long-term needs and retirement income over the client's lifetime.",
    "legacy": "Preserve and grow wealth for intergenerational transfer and inheritance.",
}
# The Liquidity bucket covers needs within this many years; a longer stated horizon is capped.
LIQUIDITY_MAX_HORIZON_YEARS = 3.0
# Dealing frequencies that return cash within days.
FAST_DEALING = {"DAILY", "WEEKLY"}
# Longevity / Legacy: cash is the Liquidity bucket's job, so templates keep at most this much cash.
INVESTED_BUCKET_MAX_CASH_PCT = 5.0
# Longevity / Legacy: an option this many growth points below what the client may hold is too cautious.
TOO_CAUTIOUS_GAP_PP = 40.0

# Liquidity-bucket templates (Cash, Fixed income, Equities, Hedge funds, Private markets, Real estate, Gold).
LIQUIDITY_TEMPLATES = (
    OptionTemplate("A", "Cash reserve", "Hold the reserve and payments due within a year in cash and money market funds.",
                   _split(100), 1.0, 1, 0.0),
    OptionTemplate("B", "Cash and short bonds", "Keep most of the bucket in cash; add short-dated bonds for a little more yield.",
                   _split(60, 40), 0.9, 1, 0.5),
    OptionTemplate("C", "Short-term income", "Earn more income on money needed in one to three years, still in short-dated, liquid holdings.",
                   _split(35, 65), 0.8, 1, 1.0),
)


@dataclass
class BucketPlan:
    """What the service needs to build one bucket's SAA."""
    ctx: BucketContext
    horizon_years: Optional[float]
    horizon_basis: str
    risk_basis: Optional[str]
    notes: list[Statement] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS[self.ctx.bucket]

    @property
    def objective(self) -> str:
        return self.ctx.objective or DEFAULT_OBJECTIVES[self.ctx.bucket]

    @property
    def templates(self) -> tuple:
        if self.ctx.bucket == "liquidity":
            return LIQUIDITY_TEMPLATES
        return tuple(_with_little_cash(t) for t in TEMPLATES)

    def single_product_cap(self, client_cap: Optional[float]) -> Optional[float]:
        """The client's single-product limit is a share of the whole portfolio. Inside a bucket that is
        part of it, the same money is a larger share of the bucket, so the cap scales up; the combined
        review enforces the client's own limit across all buckets."""
        total = self.ctx.total_3l_amount
        if client_cap is None or not total or self.ctx.amount >= total:
            return client_cap
        scaled = min(100.0, round(client_cap * total / self.ctx.amount, 2))
        if scaled > client_cap:
            self.notes.append(Statement(
                statement=f"The client's {client_cap:g}% single-product limit applies to the whole portfolio; this "
                          f"bucket is {self.ctx.amount / total:.0%} of it, so up to {scaled:g}% of the bucket may sit in "
                          "one product. The combined review checks the client's limit across all buckets.",
                basis="RULE"))
        return scaled


def _with_little_cash(t: OptionTemplate) -> OptionTemplate:
    """Longevity and Legacy: the client's cash needs sit in the Liquidity bucket, so a template keeps at
    most INVESTED_BUCKET_MAX_CASH_PCT in cash and the rest is spread pro rata over its other classes.
    (Growth and drawdown caps are applied afterwards, as for any template.)"""
    cash = t.weights.get(AssetClass.CASH, 0.0)
    if cash <= INVESTED_BUCKET_MAX_CASH_PCT:
        return t
    rest = {ac: w for ac, w in t.weights.items() if ac != AssetClass.CASH}
    scale = (100.0 - INVESTED_BUCKET_MAX_CASH_PCT) / sum(rest.values())
    weights = {AssetClass.CASH: INVESTED_BUCKET_MAX_CASH_PCT, **{ac: round(w * scale, 2) for ac, w in rest.items()}}
    return replace(t, weights=weights)


def withdraw_too_cautious(built: list, ceiling: float, plan: BucketPlan) -> None:
    """Longevity and Legacy: an option holding far fewer growth assets than the client's risk level and this
    bucket's horizon allow does not fit the bucket's purpose, so it is withdrawn (in place). The most
    growth-oriented offered option is always kept. Liquidity is exempt: caution is its purpose."""
    if plan.ctx.bucket == "liquidity":
        return
    offered = [b for b in built if b.is_offered]
    if len(offered) < 2:
        return
    keep = max(offered, key=lambda b: b.growth_share())
    for b in offered:
        g = b.growth_share()
        if b is not keep and g < ceiling - TOO_CAUTIOUS_GAP_PP:
            b.status = "NOT_SUITABLE"
            b.explanation = (
                f"Too cautious for the {plan.label} bucket: {g:.0f}% in growth assets, while the client's risk level "
                f"and this bucket's horizon allow up to {ceiling:.0f}%. The client's cash and near-term needs are "
                "held in the Liquidity bucket, so this money can be invested for the long term.")
            b.positions = []


def plan_bucket(ctx: BucketContext, a: ProfileAssessment) -> BucketPlan:
    """Applies the bucket's horizon and risk level to the assessment (in place) and says why."""
    notes: list[Statement] = []
    goal_horizon = a.shortest_horizon_years
    if ctx.horizon_years is not None:
        horizon, basis = ctx.horizon_years, f"{ctx.horizon_years:g} years, set by the Portfolio Manager for this bucket."
    elif goal_horizon is not None:
        horizon, basis = goal_horizon, f"{goal_horizon:g} years, the nearest goal assigned to this bucket."
    else:
        horizon, basis = None, "Not set: no horizon was given and no dated goal is assigned to this bucket."

    if ctx.bucket == "liquidity":
        if horizon is None:
            horizon, basis = LIQUIDITY_MAX_HORIZON_YEARS, (
                f"{LIQUIDITY_MAX_HORIZON_YEARS:g} years, the Liquidity bucket's maximum, because no shorter need was given.")
        elif horizon > LIQUIDITY_MAX_HORIZON_YEARS:
            notes.append(Statement(
                statement=f"A {horizon:g}-year horizon was given, but the Liquidity bucket covers needs within "
                          f"{LIQUIDITY_MAX_HORIZON_YEARS:g} years, so {LIQUIDITY_MAX_HORIZON_YEARS:g} is used. "
                          "Longer-dated money belongs in Longevity or Legacy.",
                basis="RULE"))
            horizon = LIQUIDITY_MAX_HORIZON_YEARS
        notes.append(Statement(
            statement="Only cash and short-dated bond templates are considered. Growth templates (Balanced to "
                      "Opportunistic) suit other buckets but not money needed within the next few years.",
            basis="RULE"))
    else:
        notes.append(Statement(
            statement=f"Cash in each option is kept to about {INVESTED_BUCKET_MAX_CASH_PCT:g}% (more only if needed to meet the "
                      f"drawdown limit) because the client's cash needs sit in the Liquidity bucket. Options holding more than {TOO_CAUTIOUS_GAP_PP:g} points fewer growth "
                      "assets than the client's risk level and this bucket's horizon allow are left out as too cautious.",
            basis="RULE"))
    if ctx.bucket != "liquidity" and horizon is None:
        a.assumptions.append(
            f"The {LABELS[ctx.bucket]} bucket has no horizon, so growth assets are capped at the medium-horizon "
            "limit. Set the bucket's horizon (or assign it a dated goal) to lift the cap.")

    # The bucket's horizon replaces the whole client's shortest goal horizon.
    a.shortest_horizon_years = horizon
    if ctx.horizon_years is not None or ctx.bucket == "liquidity":
        # Horizon is known for this bucket, so missing goal dates no longer block the long-horizon templates.
        a.missing = [m for m in a.missing if m.field != "financial_goals"]
        if not a.goals:
            a.missing.append(MissingInformation(
                field="financial_goals", severity="MINOR",
                impact=f"No dated goal is assigned to the {LABELS[ctx.bucket]} bucket; its horizon is used instead."))

    risk_basis = _apply_bucket_risk(ctx, a)
    return BucketPlan(ctx=ctx, horizon_years=horizon, horizon_basis=basis, risk_basis=risk_basis, notes=notes)


def _apply_bucket_risk(ctx: BucketContext, a: ProfileAssessment) -> Optional[str]:
    if ctx.risk_tolerance_score is None:
        return a.effective_basis
    capacity = a.capacity_effective
    if capacity is None:  # profile assessment already reports this as blocking
        return a.effective_basis
    score = ctx.risk_tolerance_score
    a.effective_level = min(score, capacity)
    label = RISK_LEVEL_LABELS.get(score, str(score))
    if score > capacity:
        basis = (f"Risk level {score} ({label}) was set for this bucket, but the client's risk capacity "
                 f"(level {capacity}) caps it.")
    else:
        basis = f"Risk level {score} ({label}) was set for this bucket's objective; within the client's capacity (level {capacity})."
    if a.willingness_level is not None and score > a.willingness_level:
        a.conflicts.append(Conflict(
            fields=["bucket.risk_tolerance_score", "risk_appetite"], severity="INFO",
            description=f"The {LABELS[ctx.bucket]} bucket's risk level ({score}) is above the client's overall risk "
                        f"appetite (level {a.willingness_level}).",
            resolution="Allowed because risk capacity covers it; confirm with the client that this objective "
                       "warrants more risk.",
        ))
    a.effective_basis = basis
    return basis


def bucket_liquidity(plan: BucketPlan, investable_assets: Optional[float]) -> LiquidityResult:
    """The whole bucket is invested. The cash reserve and near-term withdrawals are the Liquidity
    bucket's job, so they are not carved out of any bucket again."""
    amount = plan.ctx.amount
    if plan.ctx.bucket == "liquidity":
        note = (f"This bucket ({amount:,.2f}) is the client's reserve and near-term money; all of it is placed in "
                "liquid, low-volatility holdings.")
    else:
        note = (f"The cash reserve and near-term withdrawals are held in the Liquidity bucket, so the full "
                f"{plan.label} amount ({amount:,.2f}) is invested for this bucket's objective.")
    lp = LiquidityPlan(
        investable_assets=investable_assets, minimum_cash_reserve_required=None,
        reserve_already_held_outside_investable_assets=0.0, reserve_carved_out=0.0,
        near_term_withdrawals_carved_out=0.0, later_withdrawals_not_carved_out=0.0,
        eligible_portfolio_value=amount, notes=[Statement(statement=note, basis="RULE")],
    )
    return LiquidityResult(plan=lp, eligible_value=amount)


def screen_for_bucket(screening: ScreeningResult, plan: BucketPlan, base_currency: Optional[str] = None) -> ScreeningResult:
    """Liquidity bucket: drop products the client could not get back within the bucket's horizon, or
    that carry unhedged currency risk on money spent in the base currency. Other buckets keep the
    client-level screen (lock-in vs horizon and the client's currency limit are checked there)."""
    if plan.ctx.bucket != "liquidity":
        return screening
    horizon = plan.horizon_years or LIQUIDITY_MAX_HORIZON_YEARS
    by_class, excluded = {}, list(screening.excluded)
    for ac, products in screening.by_class.items():
        keep = []
        for sp in products:
            p = sp.product
            lock_years = (sp.lock_in_months or 0) / 12
            if p.recommended_horizon is not None and p.recommended_horizon > horizon:
                excluded.append((p.product_id, f"Liquidity bucket: recommended holding period of {p.recommended_horizon:g} "
                                               f"years is longer than the bucket's {horizon:g}-year horizon."))
            elif p.liquidity not in FAST_DEALING and (not sp.lock_in_months or lock_years > horizon):
                excluded.append((p.product_id, f"Liquidity bucket: {str(p.liquidity).lower()} dealing does not return "
                                               f"cash within the bucket's {horizon:g}-year horizon."))
            elif base_currency and sp.is_foreign_unhedged(base_currency):
                excluded.append((p.product_id, f"Liquidity bucket: unhedged {p.currency} exposure. Money needed soon is "
                                               f"spent in {base_currency}, so it should not carry currency risk."))
            else:
                keep.append(sp)
        by_class[ac] = keep
    return ScreeningResult(by_class=by_class, excluded=excluded)
