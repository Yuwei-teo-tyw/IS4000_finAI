"""
Screens the Product Specialist's candidates against the client's hard
constraints (restrictions, eligibility, exclusions, ESG, lock-in vs
horizon) and ranks what's left.

Every exclusion is recorded with a reason so the RM can see why a product
didn't appear - nothing is dropped silently.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.schemas.upstream import ProductCandidate
from app.agents.portfolio_manager.taxonomy import AssetClass, Liquidity, parse_asset_class, parse_period_to_months

# A product is excluded if an excluded sector exceeds this share of it;
# smaller incidental exposure (common in broad index funds) is disclosed.
EXCLUDED_SECTOR_TOLERANCE_PCT = 5.0


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


def screen_products(
    products: list[ProductCandidate],
    p: ClientProfile,
    a: ProfileAssessment,
    reference_date: date,
    stale_after_days: int,
) -> ScreeningResult:
    by_class: dict[AssetClass, list[ScreenedProduct]] = {}
    excluded: list[tuple[str, str]] = []
    restricted = {r.strip().lower() for r in (p.restricted_products or [])}
    excluded_sectors = {s.strip().lower() for s in (p.excluded_sectors or [])}
    esg_level = p.esg_preferences.level if p.esg_preferences else "None"

    for prod in products:
        reason, notes, lock_months = _screen_one(
            prod, p, a, restricted, excluded_sectors, esg_level, reference_date, stale_after_days
        )
        if reason:
            excluded.append((prod.product_id, reason))
            continue
        ac = parse_asset_class(prod.asset_class)
        by_class.setdefault(ac, []).append(ScreenedProduct(prod, ac, notes, lock_months))

    return ScreeningResult(by_class=by_class, excluded=excluded)


def _screen_one(prod, p, a, restricted, excluded_sectors, esg_level, reference_date, stale_after_days):
    notes: list[str] = []
    ac = parse_asset_class(prod.asset_class)
    if ac is None:
        return f"Unrecognised asset class '{prod.asset_class}'.", notes, None

    names = {prod.product_id.lower(), prod.product_name.lower(), (prod.product_type or "").lower()}
    if restricted & names:
        return "Listed in the client's restricted_products.", notes, None

    if a.preferred_classes is not None and ac not in a.preferred_classes:
        return f"{ac.value} is outside the client's preferred asset classes.", notes, None

    if excluded_sectors:
        if prod.sector_exposure is None:
            return "Sector exposure unknown, so the client's sector exclusions cannot be verified.", notes, None
        exposure = {k.lower(): v for k, v in prod.sector_exposure.items()}
        for sector in excluded_sectors:
            pct = exposure.get(sector, 0.0) or 0.0
            if pct > EXCLUDED_SECTOR_TOLERANCE_PCT:
                return f"{pct:.1f}% exposure to excluded sector '{sector}'.", notes, None
            if pct > 0:
                notes.append(
                    f"Contains {pct:.1f}% incidental exposure to excluded sector '{sector}' "
                    f"(below the {EXCLUDED_SECTOR_TOLERANCE_PCT:.0f}% tolerance)."
                )

    if esg_level == "Required" and prod.esg_compliant is not True:
        status = "not ESG-compliant" if prod.esg_compliant is False else "ESG status unknown"
        return f"Client requires ESG-compliant products; this product is {status}.", notes, None

    elig = prod.eligibility_requirements
    if elig:
        if elig.accredited_investor_only and p.accredited_investor is not True:
            return "Restricted to accredited investors; client is not confirmed as accredited.", notes, None
        if elig.eligible_residencies:
            if p.residency is None:
                return "Residency restriction applies and client residency is unknown.", notes, None
            if p.residency.lower() not in {r.lower() for r in elig.eligible_residencies}:
                return f"Not available to residents of {p.residency}.", notes, None
        if elig.minimum_age is not None and (p.age is None or p.age < elig.minimum_age):
            return f"Minimum investor age {elig.minimum_age} not confirmed.", notes, None

    lock_months = parse_period_to_months(prod.lock_in_period)
    if prod.lock_in_period and lock_months is None:
        return f"Lock-in period '{prod.lock_in_period}' could not be interpreted.", notes, None
    if lock_months:
        horizon = a.shortest_horizon_years
        if horizon is None and lock_months > 12:
            return "Lock-in exceeds 12 months and the client's horizon is unknown.", notes, lock_months
        if horizon is not None and lock_months / 12 > horizon:
            return (
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
        return "Unhedged foreign-currency product and the client allows no currency exposure.", notes, lock_months

    if prod.as_of_date and (reference_date - prod.as_of_date).days > stale_after_days:
        notes.append(f"Product data is stale (as of {prod.as_of_date}).")
    elif prod.as_of_date is None:
        notes.append("Product data has no as-of date.")
    if prod.data_completeness != "COMPLETE":
        notes.append(f"Product data completeness: {prod.data_completeness or 'unknown'}.")
    if esg_level == "Preferred" and prod.esg_compliant is not True:
        notes.append("Client prefers ESG-compliant products; this product is not confirmed ESG-compliant.")
    return None, notes, lock_months


def rank_products(
    candidates: list[ScreenedProduct],
    base_currency: str,
    defensiveness: float,
    esg_preferred: bool,
    effective_level: int,
) -> list[ScreenedProduct]:
    """Deterministic ranking within one asset class. Higher score first; ties
    broken by product_id so results are reproducible.

    Favours complete data, base-currency or hedged products, lower fees and
    daily liquidity. `defensiveness` (0-1) additionally penalises historical
    drawdown, so the capital-preservation option leans to lower-duration,
    lower-volatility instruments within the same asset class.
    """
    def score(sp: ScreenedProduct) -> float:
        prod = sp.product
        s = 0.0
        if prod.data_completeness == "COMPLETE":
            s += 3
        if prod.volatility is None or prod.maximum_drawdown is None:
            s -= 3
        if prod.management_fee is None:
            s -= 1
        if not sp.is_foreign_unhedged(base_currency):
            s += 2
        s -= prod.management_fee or 0
        if prod.liquidity == Liquidity.DAILY.value:
            s += 1
        if sp.lock_in_months:
            s -= 2
        if prod.risk_rating is not None and prod.risk_rating > effective_level + 1:
            s -= 2
        if esg_preferred and prod.esg_compliant:
            s += 1
        if prod.maximum_drawdown is not None:
            s -= defensiveness * abs(prod.maximum_drawdown) / 5
        return s

    return sorted(candidates, key=lambda sp: (-score(sp), sp.product_id))
