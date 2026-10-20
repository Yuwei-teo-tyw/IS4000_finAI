"""
The suitability gate: hard checks a product must pass before it can be
ranked or used. Every exclusion carries a code and a reason, so nothing is
dropped silently, and data that cannot be verified is treated as a fail.

Two layers:
- Core checks (asset class, restrictions, preferred classes, sector
  exclusions, ESG, eligibility, lock-in vs horizon, currency). Shared with
  the Portfolio Manager, which calls `screen_products()`.
- Product-level checks (risk rating vs the client's limit, single-product
  drawdown, liquidity need). Used only for recommending individual
  products. The PM builds diversified portfolios and enforces risk and
  drawdown at portfolio level, so a per-product cap would wrongly remove
  every equity product for a Balanced client.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.client import ClientProfile, PlannedWithdrawal
from app.agents.portfolio_manager.schemas.upstream import ProductCandidate
from app.agents.portfolio_manager.taxonomy import (
    AssetClass,
    Liquidity,
    parse_asset_class,
    parse_period_to_months,
)

# A product is excluded if an excluded sector exceeds this share of it;
# smaller incidental exposure (common in broad index funds) is disclosed.
EXCLUDED_SECTOR_TOLERANCE_PCT = 5.0

# Dealing terms that cannot meet a near-term cash need. AT_MATURITY is handled
# by the lock-in comparison instead, since a short deposit can still fit.
ILLIQUID_FOR_NEAR_NEED = {Liquidity.QUARTERLY.value, Liquidity.LOCKED.value}
SLOW_FOR_NEAR_NEED = {Liquidity.WEEKLY.value, Liquidity.MONTHLY.value}


@dataclass
class ScreenedProduct:
    product: ProductCandidate
    asset_class: AssetClass
    notes: list[str] = field(default_factory=list)
    lock_in_months: Optional[float] = None

    @property
    def product_id(self) -> str:
        return self.product.product_id

    def is_foreign_unhedged(self, base_currency: str) -> bool:
        return self.product.currency != base_currency and self.product.currency_hedged is not True


@dataclass
class ScreeningResult:
    by_class: dict[AssetClass, list[ScreenedProduct]]
    excluded: list[tuple[str, str]]  # (product_id, reason)


@dataclass
class GateExclusion:
    product: ProductCandidate
    code: str
    reason: str


@dataclass
class GateResult:
    eligible: list[ScreenedProduct]
    excluded: list[GateExclusion]


@dataclass
class _Context:
    profile: ClientProfile
    assessment: ProfileAssessment
    restricted: set[str]
    excluded_sectors: set[str]
    esg_level: str
    reference_date: date
    stale_after_days: int


def _context(p: ClientProfile, a: ProfileAssessment, reference_date: date, stale_after_days: int) -> _Context:
    return _Context(
        profile=p,
        assessment=a,
        restricted={r.strip().lower() for r in (p.restricted_products or [])},
        excluded_sectors={s.strip().lower() for s in (p.excluded_sectors or [])},
        esg_level=p.esg_preferences.level if p.esg_preferences else "None",
        reference_date=reference_date,
        stale_after_days=stale_after_days,
    )


# --- Shared with the Portfolio Manager ---------------------------------------

def screen_products(
    products: list[ProductCandidate],
    p: ClientProfile,
    a: ProfileAssessment,
    reference_date: date,
    stale_after_days: int,
) -> ScreeningResult:
    """Core checks only, grouped by asset class (the Portfolio Manager's view)."""
    ctx = _context(p, a, reference_date, stale_after_days)
    by_class: dict[AssetClass, list[ScreenedProduct]] = {}
    excluded: list[tuple[str, str]] = []
    for prod in products:
        code, reason, notes, lock_months = _core_checks(prod, ctx)
        if code:
            excluded.append((prod.product_id, reason))
            continue
        ac = parse_asset_class(prod.asset_class)
        by_class.setdefault(ac, []).append(ScreenedProduct(prod, ac, notes, lock_months))
    return ScreeningResult(by_class=by_class, excluded=excluded)


def _core_checks(prod: ProductCandidate, ctx: _Context):
    """Returns (code, reason, notes, lock_in_months); code is None when the product passes."""
    p, a = ctx.profile, ctx.assessment
    notes: list[str] = []
    ac = parse_asset_class(prod.asset_class)
    if ac is None:
        return "DATA_INVALID", f"Unrecognised asset class '{prod.asset_class}'.", notes, None

    names = {prod.product_id.lower(), prod.product_name.lower(), (prod.product_type or "").lower()}
    if ctx.restricted & names:
        return "RESTRICTED", "Listed in the client's restricted_products.", notes, None

    if a.preferred_classes is not None and ac not in a.preferred_classes:
        return "NOT_PREFERRED", f"{ac.value} is outside the client's preferred asset classes.", notes, None

    if ctx.excluded_sectors:
        if prod.sector_exposure is None:
            return "SECTOR_EXCLUDED", "Sector exposure unknown, so the client's sector exclusions cannot be verified.", notes, None
        exposure = {k.lower(): v for k, v in prod.sector_exposure.items()}
        for sector in ctx.excluded_sectors:
            pct = exposure.get(sector, 0.0) or 0.0
            if pct > EXCLUDED_SECTOR_TOLERANCE_PCT:
                return "SECTOR_EXCLUDED", f"{pct:.1f}% exposure to excluded sector '{sector}'.", notes, None
            if pct > 0:
                notes.append(
                    f"Contains {pct:.1f}% incidental exposure to excluded sector '{sector}' "
                    f"(below the {EXCLUDED_SECTOR_TOLERANCE_PCT:.0f}% tolerance)."
                )

    if ctx.esg_level == "Required" and prod.esg_compliant is not True:
        status = "not ESG-compliant" if prod.esg_compliant is False else "ESG status unknown"
        return "ESG", f"Client requires ESG-compliant products; this product is {status}.", notes, None

    elig = prod.eligibility_requirements
    if elig:
        if elig.accredited_investor_only and p.accredited_investor is not True:
            return "ELIGIBILITY", "Restricted to accredited investors; client is not confirmed as accredited.", notes, None
        if elig.eligible_residencies:
            if p.residency is None:
                return "ELIGIBILITY", "Residency restriction applies and client residency is unknown.", notes, None
            if p.residency.lower() not in {r.lower() for r in elig.eligible_residencies}:
                return "ELIGIBILITY", f"Not available to residents of {p.residency}.", notes, None
        if elig.minimum_age is not None and (p.age is None or p.age < elig.minimum_age):
            return "ELIGIBILITY", f"Minimum investor age {elig.minimum_age} not confirmed.", notes, None

    lock_months = parse_period_to_months(prod.lock_in_period)
    if prod.lock_in_period and lock_months is None:
        return "LIQUIDITY", f"Lock-in period '{prod.lock_in_period}' could not be interpreted.", notes, None
    if lock_months:
        horizon = a.shortest_horizon_years
        if horizon is None and lock_months > 12:
            return "LIQUIDITY", "Lock-in exceeds 12 months and the client's horizon is unknown.", notes, lock_months
        if horizon is not None and lock_months / 12 > horizon:
            return (
                "LIQUIDITY",
                f"Lock-in of {prod.lock_in_period} exceeds the shortest goal horizon ({horizon:g} years).",
                notes, lock_months,
            )
        notes.append(f"Lock-in period of {prod.lock_in_period}; funds are not accessible before then without penalty.")

    if (
        p.maximum_currency_exposure == 0
        and p.base_currency
        and prod.currency != p.base_currency
        and prod.currency_hedged is not True
    ):
        return "CURRENCY", "Unhedged foreign-currency product and the client allows no currency exposure.", notes, lock_months

    if prod.as_of_date and (ctx.reference_date - prod.as_of_date).days > ctx.stale_after_days:
        notes.append(f"Product data is stale (as of {prod.as_of_date}).")
    elif prod.as_of_date is None:
        notes.append("Product data has no as-of date.")
    if prod.data_completeness != "COMPLETE":
        notes.append(f"Product data completeness: {prod.data_completeness or 'unknown'}.")
    if ctx.esg_level == "Preferred" and prod.esg_compliant is not True:
        notes.append("Client prefers ESG-compliant products; this product is not confirmed ESG-compliant.")
    return None, None, notes, lock_months


# --- Product Recommender: core + product-level checks -------------------------

def gate(
    products: list[ProductCandidate],
    p: ClientProfile,
    a: ProfileAssessment,
    reference_date: date,
    stale_after_days: int,
    liquidity_need_months: int = 12,
    drawdown_hard_limit: bool = False,
) -> GateResult:
    """Every product ends up in exactly one of `eligible` or `excluded`."""
    ctx = _context(p, a, reference_date, stale_after_days)
    need_months = near_term_need_months(p, reference_date, liquidity_need_months)
    eligible: list[ScreenedProduct] = []
    excluded: list[GateExclusion] = []
    for prod in products:
        code, reason, notes, lock_months = _core_checks(prod, ctx)
        if not code:
            code, reason = _product_checks(prod, ctx, notes, lock_months, need_months, drawdown_hard_limit)
        if code:
            excluded.append(GateExclusion(prod, code, reason))
        else:
            eligible.append(ScreenedProduct(prod, parse_asset_class(prod.asset_class), notes, lock_months))
    return GateResult(eligible=eligible, excluded=excluded)


def _product_checks(prod, ctx: _Context, notes: list[str], lock_months, need_months, drawdown_hard_limit):
    """Returns (code, reason) or (None, None); appends pass notes in place."""
    level = ctx.assessment.effective_level
    if prod.risk_rating is None:
        return "DATA_INVALID", "Risk rating missing, so suitability against the client's risk limit cannot be verified."
    if level is None:
        return "RISK_UNKNOWN", "The client's risk level is not established, so no product can be checked against it."
    if prod.risk_rating > level:
        return "RISK_ABOVE_LIMIT", f"Risk {prod.risk_rating} of 5 is above the client's limit of {level}."
    if prod.risk_rating == level:
        notes.append(f"Risk {prod.risk_rating} of 5 is at the client's limit.")

    limit = ctx.profile.maximum_acceptable_drawdown
    if limit is not None and prod.maximum_drawdown is not None and abs(prod.maximum_drawdown) > limit:
        text = (f"Historical drawdown of {prod.maximum_drawdown:g}% on its own is larger than the client's "
                f"portfolio limit of -{limit:g}%")
        if drawdown_hard_limit:
            return "DRAWDOWN", text + "."
        notes.append(text + "; suitable only as part of a diversified portfolio.")

    if need_months is not None:
        if prod.liquidity in ILLIQUID_FOR_NEAR_NEED:
            return "LIQUIDITY_NEED", (f"{prod.liquidity.title()} dealing cannot meet the client's cash need "
                                      f"within {need_months:g} months.")
        if lock_months and lock_months > need_months:
            return "LIQUIDITY_NEED", (f"Lock-in of {prod.lock_in_period} runs past the client's cash need "
                                      f"within {need_months:g} months.")
        if prod.liquidity in SLOW_FOR_NEAR_NEED:
            notes.append(f"{prod.liquidity.title()} dealing; check timing against the client's cash need "
                         f"within {need_months:g} months.")
    return None, None


def near_term_need_months(p: ClientProfile, reference_date: date, window_months: int) -> Optional[float]:
    """Months until the earliest dated withdrawal inside the window, else None.

    Undated withdrawals (a plain amount) carry no timing, so they do not
    trigger the check; the PM's liquidity plan already ring-fences them.
    """
    if not isinstance(p.planned_withdrawals, list):
        return None
    months = [m for m in (_months_until(w, reference_date) for w in p.planned_withdrawals) if m is not None]
    near = [m for m in months if m <= window_months]
    return min(near) if near else None


def _months_until(w: PlannedWithdrawal, reference_date: date) -> Optional[float]:
    if w.months_from_now is not None:
        return w.months_from_now
    if w.expected_date is not None:
        return max(0.0, (w.expected_date - reference_date).days / 30.4)
    return None
