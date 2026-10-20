"""
Product screening for the Portfolio Manager.

The hard checks (restrictions, eligibility, exclusions, ESG, lock-in vs
horizon, currency) live in the Product Recommender's suitability gate, so
both agents apply one implementation. This module re-exports it for the
PM's construction code and keeps the PM's within-class ranking.

Every exclusion is recorded with a reason so the RM can see why a product
didn't appear - nothing is dropped silently.
"""
from app.agents.portfolio_manager.taxonomy import Liquidity
from app.agents.product_recommender.suitability import (  # noqa: F401
    EXCLUDED_SECTOR_TOLERANCE_PCT,
    ScreenedProduct,
    ScreeningResult,
    screen_products,
)


def rank_products(
    candidates: list[ScreenedProduct],
    base_currency: str,
    defensiveness: float,
    esg_preferred: bool,
    effective_level: int,
) -> list[ScreenedProduct]:
    """Deterministic ranking within one asset class. Higher score first; ties
    broken by product_id so results are reproducible.

    Favours complete data, base-currency or hedged products and daily
    liquidity. `defensiveness` (0-1) additionally penalises historical
    drawdown, so the capital-preservation option leans to lower-duration,
    lower-volatility instruments within the same asset class.

    Fees are never part of the score (suitability first; fees are shown for
    information only), matching the Product Recommender's rule.
    """
    def score(sp: ScreenedProduct) -> float:
        prod = sp.product
        s = 0.0
        if prod.data_completeness == "COMPLETE":
            s += 3
        if prod.volatility is None or prod.maximum_drawdown is None:
            s -= 3
        if not sp.is_foreign_unhedged(base_currency):
            s += 2
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
