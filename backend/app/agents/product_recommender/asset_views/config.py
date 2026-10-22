"""
Which Market Researcher series drive each asset class and segment, and how.

A Signal reads one indicator (FRED id from `indicators` or a ticker from
`market_snapshot`) in one of three ways:

  level     where today's value sits in its 10-year range: (percentile - 50) / 50
  change    the 3-month change, divided by `scale` (the move counted as "large")
  relative  the 3-month change minus that of `vs`, divided by `scale`

Each reading is clipped to [-1, 1], then multiplied by `direction` (+1 if a
higher reading supports the asset class, -1 if it weighs on it) and `weight`.
"""
from dataclasses import dataclass
from typing import Literal, Optional

from app.agents.portfolio_agent.taxonomy import AssetClass


@dataclass(frozen=True)
class Signal:
    id: str
    direction: Literal[1, -1]
    weight: float
    basis: Literal["level", "change", "relative"] = "level"
    scale: float = 1.0
    vs: Optional[str] = None
    why: str = ""  # one clause: why this series matters for the class


@dataclass(frozen=True)
class Segment:
    group: str
    name: str
    signals: tuple[Signal, ...] = ()
    no_data_reason: str = "Not enough data to differentiate"


@dataclass(frozen=True)
class AssetClassSpec:
    signals: tuple[Signal, ...]
    segments: tuple[Segment, ...]
    low_coverage: bool = False  # confidence capped at Low: the data describes the environment, not the class


# Stance cut-offs on the [-1, 1] score. Not yet calibrated on historical runs (see NOTES.md).
BUY_AT = 0.2
SELL_AT = -0.2
# A segment is preferred / least preferred relative to its own asset class's score.
SEGMENT_MARGIN = 0.15
# Below this share of mapped series available, the view is Hold / Low with "insufficient evidence".
MIN_COVERAGE = 0.5
REGIME_WEIGHT = 0.15
REGIME_CONFIDENCE = {"low": 0.5, "medium": 0.75, "high": 1.0}

# How each cycle phase leans for each class, in [-1, 1].
REGIME_TILT: dict[str, dict[AssetClass, float]] = {
    "early_expansion": {AssetClass.EQUITIES: 1.0, AssetClass.FIXED_INCOME: 0.0, AssetClass.CASH: -1.0, AssetClass.GOLD: 0.0,
                        AssetClass.REAL_ESTATE: 0.5, AssetClass.HEDGE_FUNDS: 0.0, AssetClass.PRIVATE_MARKETS: 0.5},
    "late_expansion": {AssetClass.EQUITIES: 0.3, AssetClass.FIXED_INCOME: 0.3, AssetClass.CASH: 0.0, AssetClass.GOLD: 0.3,
                       AssetClass.REAL_ESTATE: -0.2, AssetClass.HEDGE_FUNDS: 0.3, AssetClass.PRIVATE_MARKETS: 0.0},
    "recession": {AssetClass.EQUITIES: -1.0, AssetClass.FIXED_INCOME: 1.0, AssetClass.CASH: 0.5, AssetClass.GOLD: 0.5,
                  AssetClass.REAL_ESTATE: -0.5, AssetClass.HEDGE_FUNDS: 0.0, AssetClass.PRIVATE_MARKETS: -0.5},
    "late_recession": {AssetClass.EQUITIES: 0.5, AssetClass.FIXED_INCOME: 0.5, AssetClass.CASH: -0.5, AssetClass.GOLD: 0.0,
                       AssetClass.REAL_ESTATE: 0.0, AssetClass.HEDGE_FUNDS: 0.0, AssetClass.PRIVATE_MARKETS: 0.0},
}

NO_SG_DATA = "No SGD/Asia data yet (the Market Researcher covers the US only)"

S = Signal
SECTORS = (("XLK", "Technology"), ("XLF", "Financials"), ("XLV", "Health care"), ("XLI", "Industrials"), ("XLE", "Energy"),
           ("XLY", "Consumer discretionary"), ("XLP", "Consumer staples"), ("XLU", "Utilities"), ("XLC", "Communication services"),
           ("XLB", "Materials"))

SPECS: dict[AssetClass, AssetClassSpec] = {
    AssetClass.CASH: AssetClassSpec(
        signals=(
            S("DFF", 1, 1.0, why="the policy rate sets cash yields"),
            S("DGS3MO", 1, 0.8, why="bill yields set what cash earns"),
            S("DFF", 1, 0.6, "change", 0.5, why="policy rate moves change what cash earns"),
            S("CPILFESL", -1, 0.8, why="core inflation sets the real return on cash"),
        ),
        segments=(
            Segment("Tenor", "Overnight / money market", (S("DFF", 1, 1.0), S("DFF", 1, 0.8, "change", 0.5))),
            Segment("Tenor", "3 to 12 month deposits and bills", (S("DGS3MO", 1, 1.0), S("T10Y3M", -1, 0.6))),
        ),
    ),
    AssetClass.FIXED_INCOME: AssetClassSpec(
        signals=(
            S("DGS10", 1, 1.0, why="the starting yield sets future income"),
            S("DGS10", -1, 0.8, "change", 0.5, why="yield moves drive bond prices"),
            S("DFII10", 1, 0.6, why="real yields show the value left after inflation"),
            S("CPILFESL", -1, 0.6, "change", 0.3, why="the inflation trend drives yields"),
            S("BAMLC0A0CM", 1, 0.5, why="investment-grade spreads are the pay for credit risk"),
            S("BAMLH0A0HYM2", 1, 0.4, why="high-yield spreads are the pay for credit risk"),
            S("T10YIE", -1, 0.4, "change", 0.2, why="inflation expectations drive yields"),
        ),
        segments=(
            Segment("Duration", "Short (up to 3 years)", (S("DGS2", 1, 1.0), S("DFF", -1, 0.8, "change", 0.5))),
            Segment("Duration", "Intermediate (3 to 10 years)", (S("DGS10", 1, 1.0), S("DGS10", -1, 0.8, "change", 0.5))),
            Segment("Duration", "Long (over 10 years)", (S("DGS30", 1, 1.0), S("DGS30", -1, 0.8, "change", 0.5), S("T10YIE", -1, 0.6, "change", 0.2))),
            Segment("Quality", "Government", (S("DGS10", 1, 1.0), S("VIXCLS", 1, 0.5))),
            Segment("Quality", "Investment grade", (S("BAMLC0A0CM", 1, 1.0), S("BAA10Y", 1, 0.6))),
            Segment("Quality", "High yield", (S("BAMLH0A0HYM2", 1, 1.0), S("NFCI", -1, 0.6), S("VIXCLS", -1, 0.5))),
            Segment("Region", "US", (S("DGS10", 1, 1.0), S("DGS10", -1, 0.8, "change", 0.5))),
            Segment("Region", "Asia / SGD", no_data_reason=NO_SG_DATA),
        ),
    ),
    AssetClass.EQUITIES: AssetClassSpec(
        signals=(
            S("SPY", 1, 1.0, "change", 10.0, why="price momentum in US large caps"),
            S("NFCI", -1, 0.8, why="financial conditions set the cost and availability of capital"),
            S("VIXCLS", -1, 0.6, why="volatility reflects market stress"),
            S("PAYEMS", 1, 0.5, why="job growth drives earnings"),
            S("UNRATE", -1, 0.5, "change", 0.3, why="the unemployment trend signals the direction of growth"),
            S("DGS10", -1, 0.4, why="bond yields compete with equities for capital"),
        ),
        segments=(
            Segment("Region", "US large cap", (S("SPY", 1, 1.0, "change", 10.0), S("VIXCLS", -1, 0.5))),
            Segment("Region", "US growth / technology", (S("QQQ", 1, 1.0, "relative", 5.0, "SPY"),)),
            Segment("Region", "US small cap", (S("IWM", 1, 1.0, "relative", 5.0, "SPY"), S("NFCI", -1, 0.5))),
            Segment("Region", "Developed ex-US", (S("EFA", 1, 1.0, "relative", 5.0, "SPY"), S("DX-Y.NYB", -1, 0.5, "change", 5.0))),
            Segment("Region", "Emerging markets", (S("EEM", 1, 1.0, "relative", 5.0, "SPY"), S("DX-Y.NYB", -1, 0.6, "change", 5.0))),
            Segment("Region", "Asia / Singapore", no_data_reason=NO_SG_DATA),
            *(Segment("Sector", name, (S(tk, 1, 1.0, "relative", 5.0, "SPY"),)) for tk, name in SECTORS),
        ),
    ),
    AssetClass.GOLD: AssetClassSpec(
        signals=(
            S("GLD", 1, 1.0, "change", 10.0, why="price momentum in gold"),
            S("DFII10", -1, 0.8, why="real yields are the cost of holding gold, which pays no income"),
            S("DX-Y.NYB", -1, 0.6, "change", 5.0, why="gold is priced in US dollars"),
            S("VIXCLS", 1, 0.4, why="market stress drives demand for gold"),
        ),
        segments=(
            Segment("Exposure", "Physical gold / ETF", (S("GLD", 1, 1.0, "change", 10.0), S("DFII10", -1, 0.8))),
            Segment("Role", "Portfolio hedge", (S("VIXCLS", 1, 1.0), S("STLFSI4", 1, 0.8))),
        ),
    ),
    AssetClass.REAL_ESTATE: AssetClassSpec(
        signals=(
            S("XLRE", 1, 1.0, "change", 10.0, why="price momentum in listed REITs"),
            S("DGS10", -1, 0.8, why="bond yields set financing costs and compete with REIT yields"),
            S("DGS10", -1, 0.6, "change", 0.5, why="yield moves drive property valuations"),
            S("BAA10Y", -1, 0.4, why="corporate spreads set borrowing costs"),
        ),
        segments=(
            Segment("Region", "US listed REITs", (S("XLRE", 1, 1.0, "relative", 5.0, "SPY"), S("DGS10", -1, 0.6, "change", 0.5))),
            Segment("Region", "Asia / Singapore REITs", no_data_reason=NO_SG_DATA),
        ),
    ),
    AssetClass.HEDGE_FUNDS: AssetClassSpec(
        signals=(
            S("VIXCLS", 1, 0.6, why="volatility sets how much active managers have to trade"),
            S("STLFSI4", -1, 0.6, why="financial stress affects leveraged strategies"),
            S("NFCI", -1, 0.4, why="funding conditions set the cost of leverage"),
        ),
        segments=(
            Segment("Strategy", "Trend-following / macro"),
            Segment("Strategy", "Event-driven"),
            Segment("Strategy", "Multi-strategy"),
        ),
        low_coverage=True,
    ),
    AssetClass.PRIVATE_MARKETS: AssetClassSpec(
        signals=(
            S("BAMLH0A0HYM2", -1, 0.6, why="high-yield spreads set financing costs for buyouts"),
            S("NFCI", -1, 0.6, why="financial conditions drive deal activity"),
            S("DGS10", -1, 0.4, why="rates set the hurdle for private valuations"),
        ),
        segments=(
            Segment("Strategy", "Private equity"),
            Segment("Strategy", "Private credit"),
        ),
        low_coverage=True,
    ),
}

# Which segment group a shelf product is mapped to when showing how to implement the view.
IMPLEMENTATION_GROUP: dict[AssetClass, str] = {
    AssetClass.CASH: "Tenor", AssetClass.FIXED_INCOME: "Quality", AssetClass.EQUITIES: "Region", AssetClass.GOLD: "Exposure",
    AssetClass.REAL_ESTATE: "Region", AssetClass.HEDGE_FUNDS: "Strategy", AssetClass.PRIVATE_MARKETS: "Strategy",
}
