"""
How an asset-class view can be implemented from the shared shelf, and what
one client can actually access. The client lens reuses the suitability gate;
eligibility is never reimplemented here. Fees appear only as a display-only
summary.
"""
from collections import Counter
from datetime import date
from statistics import median
from typing import Optional

from app.agents.portfolio_agent.engine.profile_assessment import assess_profile
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.taxonomy import AssetClass, parse_asset_class
from app.agents.product_recommender.asset_views.schemas import (
    ClientLens,
    FeeSummary,
    Implementation,
    ImplementationProduct,
)
from app.agents.product_recommender.config import Settings
from app.agents.product_recommender.schemas import ShelfProduct
from app.agents.product_recommender.suitability import gate

GLOBAL = "Global (multi-region)"


def _region_share(prod: ShelfProduct, *keys: str) -> float:
    geo = prod.geographic_exposure or {}
    return sum(v for k, v in geo.items() if any(key in k.lower() for key in keys))


def product_segment(ac: AssetClass, prod: ShelfProduct) -> str:
    """The one segment a product expresses (its asset class's implementation group)."""
    text = f"{prod.product_name} {prod.sub_asset_class or ''} {prod.product_type or ''}".lower()
    if ac == AssetClass.CASH:
        return "Overnight / money market" if "money market" in text else "3 to 12 month deposits and bills"
    if ac == AssetClass.FIXED_INCOME:
        if "high yield" in text or "high-yield" in text:
            return "High yield"
        return "Government" if "government" in text or "treasury" in text else "Investment grade"
    if ac == AssetClass.EQUITIES:
        if _region_share(prod, "singapore", "asia", "hong kong", "australia") >= 50:
            return "Asia / Singapore"
        if _region_share(prod, "emerging") >= 50:
            return "Emerging markets"
        if _region_share(prod, "united states") >= 60:
            return "US large cap"
        return GLOBAL
    if ac == AssetClass.REAL_ESTATE:
        if _region_share(prod, "singapore", "asia") >= 50:
            return "Asia / Singapore REITs"
        return "US listed REITs" if _region_share(prod, "united states") >= 60 else GLOBAL
    if ac == AssetClass.HEDGE_FUNDS:
        if "trend" in text or "macro" in text:
            return "Trend-following / macro"
        return "Event-driven" if "event" in text else "Multi-strategy"
    if ac == AssetClass.PRIVATE_MARKETS:
        return "Private credit" if "credit" in text else "Private equity"
    return "Physical gold / ETF"


def in_class(ac: AssetClass, products: list[ShelfProduct]) -> list[ShelfProduct]:
    return [p for p in products if parse_asset_class(p.asset_class) == ac]


def implementation(ac: AssetClass, products: list[ShelfProduct]) -> Implementation:
    items = [
        ImplementationProduct(product_id=p.product_id, product_name=p.product_name, segment=product_segment(ac, p),
                              risk_rating=p.risk_rating, liquidity=p.liquidity, currency=p.currency, currency_hedged=p.currency_hedged)
        for p in sorted(products, key=lambda p: p.product_id)
    ]
    fees = [p.management_fee for p in products if p.management_fee is not None]
    return Implementation(products=items, fees=FeeSummary(
        min_pct=min(fees) if fees else None, median_pct=round(median(fees), 2) if fees else None, max_pct=max(fees) if fees else None))


def client_lens(ac: AssetClass, products: list[ShelfProduct], client_id: str, profile: ClientProfile,
                today: date, settings: Settings) -> ClientLens:
    a = assess_profile(profile, None, today)
    result = gate(products, profile, a, a.reference_date, settings.product_stale_after_days,
                  liquidity_need_months=settings.liquidity_need_months, drawdown_hard_limit=settings.drawdown_hard_limit)
    current: Optional[float] = None
    for label, pct in (profile.current_asset_allocation or {}).items():
        if parse_asset_class(label) == ac:
            current = pct
    return ClientLens(
        client_id=client_id,
        risk_level=a.effective_level,
        eligible=len(result.eligible),
        excluded=dict(sorted(Counter(x.code for x in result.excluded).items())),
        accessible_segments=sorted({product_segment(ac, sp.product) for sp in result.eligible}),
        current_weight_pct=current,
    )
