"""
Shared vocabulary: asset classes, risk levels, liquidity tiers, and the
normalisers that map free-text RM/upstream labels onto them.

The seven asset classes and the growth-asset limits mirror the PM SAA
builder in the frontend (frontend/src/pages/ic/icHelpers.ts), so the
agent's numbers and the SAA screen use one model.
"""
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    CASH = "Cash"
    FIXED_INCOME = "Fixed income"
    EQUITIES = "Equities"
    HEDGE_FUNDS = "Hedge funds"
    PRIVATE_MARKETS = "Private markets"
    REAL_ESTATE = "Real estate"
    GOLD = "Gold"


# Order used by SAA template splits (matches the frontend's ASSETS list).
ASSET_CLASS_ORDER = [
    AssetClass.CASH,
    AssetClass.FIXED_INCOME,
    AssetClass.EQUITIES,
    AssetClass.HEDGE_FUNDS,
    AssetClass.PRIVATE_MARKETS,
    AssetClass.REAL_ESTATE,
    AssetClass.GOLD,
]

# Growth assets = equities + hedge funds + private markets, as in the SAA
# builder. Real estate and gold count as diversifiers; their risk is still
# captured by the stress-drawdown check.
GROWTH_WEIGHT = {
    AssetClass.CASH: 0.0,
    AssetClass.FIXED_INCOME: 0.0,
    AssetClass.EQUITIES: 1.0,
    AssetClass.HEDGE_FUNDS: 1.0,
    AssetClass.PRIVATE_MARKETS: 1.0,
    AssetClass.REAL_ESTATE: 0.0,
    AssetClass.GOLD: 0.0,
}

DEFENSIVE_CLASSES = [AssetClass.CASH, AssetClass.FIXED_INCOME]

_ASSET_CLASS_SYNONYMS = {
    "cash": AssetClass.CASH,
    "cash and cash equivalents": AssetClass.CASH,
    "money market": AssetClass.CASH,
    "fixed income": AssetClass.FIXED_INCOME,
    "bonds": AssetClass.FIXED_INCOME,
    "government bonds": AssetClass.FIXED_INCOME,
    "corporate bonds": AssetClass.FIXED_INCOME,
    "investment-grade corporate bonds": AssetClass.FIXED_INCOME,
    "equities": AssetClass.EQUITIES,
    "equity": AssetClass.EQUITIES,
    "stocks": AssetClass.EQUITIES,
    "diversified equities": AssetClass.EQUITIES,
    "dividend equities": AssetClass.EQUITIES,
    "hedge funds": AssetClass.HEDGE_FUNDS,
    "hedge fund": AssetClass.HEDGE_FUNDS,
    "private markets": AssetClass.PRIVATE_MARKETS,
    "private equity": AssetClass.PRIVATE_MARKETS,
    "private credit": AssetClass.PRIVATE_MARKETS,
    "real estate": AssetClass.REAL_ESTATE,
    "reits": AssetClass.REAL_ESTATE,
    "reit": AssetClass.REAL_ESTATE,
    "property": AssetClass.REAL_ESTATE,
    "gold": AssetClass.GOLD,
    "commodities": AssetClass.GOLD,
    "gold & commodities": AssetClass.GOLD,
}

# Labels that cover several classes at once.
_GROUP_SYNONYMS = {
    "alternatives": {AssetClass.HEDGE_FUNDS, AssetClass.PRIVATE_MARKETS},
    "alternative investments": {AssetClass.HEDGE_FUNDS, AssetClass.PRIVATE_MARKETS},
}


def parse_asset_class(label: str | None) -> Optional[AssetClass]:
    if not label:
        return None
    return _ASSET_CLASS_SYNONYMS.get(label.strip().lower())


def resolve_preference(label: str) -> set[AssetClass] | None:
    """Map one `preferred_asset_classes` entry to the asset classes it
    covers. None for unrecognised labels so the caller can flag them."""
    key = label.strip().lower()
    if key in _GROUP_SYNONYMS:
        return set(_GROUP_SYNONYMS[key])
    exact = parse_asset_class(label)
    return {exact} if exact else None


# --- Risk levels -------------------------------------------------------------
# One 1-5 ordinal scale for risk appetite, risk capacity and the tolerance
# score (the frontend's client risk limit / riskCap uses the same scale).

# The frontend's risk categories map onto the client risk limit (riskCap)
# as Conservative/Moderately conservative 1-2, Moderate or Balanced 3,
# Growth 4, Aggressive 5 (both Moderate and Balanced clients have limit 3).
RISK_LEVEL_LABELS = {
    1: "Conservative",
    2: "Moderately conservative",
    3: "Moderate / Balanced",
    4: "Growth",
    5: "Aggressive",
}

_APPETITE_SYNONYMS = {
    "conservative": 1, "low": 1, "very low": 1,
    "moderately conservative": 2, "cautious": 2, "low-moderate": 2, "low to moderate": 2,
    "moderate": 3, "balanced": 3, "medium": 3,
    "growth": 4, "moderately aggressive": 4, "moderate-high": 4, "moderately high": 4,
    "aggressive": 5, "high": 5, "very high": 5,
}

_CAPACITY_SYNONYMS = {
    "very low": 1, "low": 1,
    "low-moderate": 2, "low to moderate": 2, "moderately low": 2,
    "moderate": 3, "medium": 3, "balanced": 3,
    "moderately high": 4, "moderate-high": 4,
    "high": 5, "very high": 5,
}


def parse_risk_appetite(label: str | None) -> Optional[int]:
    return _APPETITE_SYNONYMS.get(label.strip().lower()) if label else None


def parse_risk_capacity(label: str | None) -> Optional[int]:
    return _CAPACITY_SYNONYMS.get(label.strip().lower()) if label else None


# Maximum growth-asset share per effective risk level - the same table the
# SAA builder enforces (growthLimit in icHelpers.ts).
GROWTH_CEILING_BY_RISK_LEVEL = {1: 15.0, 2: 30.0, 3: 50.0, 4: 70.0, 5: 90.0}


def risk_label_for_stress_drawdown(drawdown_pct: float) -> tuple[int, str]:
    """Bucket an estimated stress drawdown (positive %) into a 1-5 risk level."""
    if drawdown_pct <= 3:
        return 1, "Low"
    if drawdown_pct <= 8:
        return 2, "Low-Moderate"
    if drawdown_pct <= 15:
        return 3, "Moderate"
    if drawdown_pct <= 25:
        return 4, "Moderate-High"
    return 5, "High"


# --- Liquidity ---------------------------------------------------------------

class Liquidity(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    AT_MATURITY = "AT_MATURITY"
    LOCKED = "LOCKED"


HIGH_LIQUIDITY = {Liquidity.DAILY}


def parse_period_to_months(text: str | None) -> Optional[float]:
    """'6 months' -> 6, '3 years' -> 36, 'none'/'0' -> 0. None if unparseable."""
    if text is None:
        return None
    t = text.strip().lower()
    if t in {"", "none", "no lock-in", "0"}:
        return 0.0
    parts = t.split()
    try:
        n = float(parts[0])
    except (ValueError, IndexError):
        return None
    unit = parts[1] if len(parts) > 1 else "months"
    if unit.startswith("year"):
        return n * 12
    if unit.startswith("month"):
        return n
    if unit.startswith("week"):
        return n / 4.345
    if unit.startswith("day"):
        return n / 30.4
    return None
