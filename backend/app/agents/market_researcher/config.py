"""
Static configuration for the market researcher agent: which series and
symbols to pull, every event threshold and regime weight, cache TTLs,
staleness grace periods, and timeouts.

Tune behavior here, not in code - the backtest (backtest.py) is the
feedback loop for the regime weights. Env-driven settings (API keys,
output dir, concurrency) are read lazily via `load_settings()` so nothing
is captured at import time, before app.py's `load_dotenv()` has run.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Frequency = Literal["D", "W", "M", "Q"]
Transform = Literal["level", "yoy", "diff_3m_avg"]
Signal = Literal[
    "bullish_growth", "bearish_growth", "inflationary", "disinflationary",
    "tightening", "easing", "neutral",
]

SCHEMA_VERSION = "1.4"  # 1.1: Indicator.stats_window_years; 1.2: Regime.in_recession_prob, Regime.scores;
# 1.3: plan, planned_indicators, planned_market, event_explanations (all optional);
# 1.4: quality, EventExplanation.cited_sources (optional)
SUPPORTED_REGIONS = ("US",)


@dataclass(frozen=True)
class SeriesSpec:
    """One FRED series, how to present it, and how to read its direction.

    `transform` decides what `Indicator.value` shows: the raw level, the
    year-over-year % change (price indexes, activity levels), or the 3-month
    average of monthly differences (payrolls). `up_signal`/`down_signal`
    fire when the transformed value's `signal_change` move exceeds
    `signal_threshold` in that direction; otherwise the signal is neutral.
    """
    id: str
    name: str
    unit: str
    frequency: Frequency
    category: str
    transform: Transform = "level"
    up_signal: Signal = "neutral"
    down_signal: Signal = "neutral"
    signal_change: str = "1m"
    signal_threshold: float = 0.0
    backtest_only: bool = False
    # Shown to the query planner for catalog entries (EXTRA_SERIES_CATALOG).
    description: str = ""
    tags: tuple[str, ...] = ()


# --- US series map (guide §3.1) -------------------------------------------
# Adding a region later means adding another map like this one, not new code.

US_SERIES: tuple[SeriesSpec, ...] = (
    # Yields
    SeriesSpec("DGS3MO", "3-Month Treasury Yield", "%", "D", "rates", up_signal="tightening", down_signal="easing", signal_threshold=0.15),
    SeriesSpec("DGS2", "2-Year Treasury Yield", "%", "D", "rates", up_signal="tightening", down_signal="easing", signal_threshold=0.15),
    SeriesSpec("DGS10", "10-Year Treasury Yield", "%", "D", "rates", up_signal="tightening", down_signal="easing", signal_threshold=0.15),
    SeriesSpec("DGS30", "30-Year Treasury Yield", "%", "D", "rates", up_signal="tightening", down_signal="easing", signal_threshold=0.15),
    # Curve
    SeriesSpec("T10Y2Y", "10Y-2Y Treasury Spread", "pp", "D", "curve", up_signal="bullish_growth", down_signal="bearish_growth", signal_change="3m", signal_threshold=0.20),
    SeriesSpec("T10Y3M", "10Y-3M Treasury Spread", "pp", "D", "curve", up_signal="bullish_growth", down_signal="bearish_growth", signal_change="3m", signal_threshold=0.20),
    # Policy rate
    SeriesSpec("DFF", "Effective Federal Funds Rate", "%", "D", "policy", up_signal="tightening", down_signal="easing", signal_change="3m", signal_threshold=0.10),
    SeriesSpec("DFEDTARU", "Fed Funds Target Range Upper", "%", "D", "policy", up_signal="tightening", down_signal="easing", signal_change="3m", signal_threshold=0.10),
    SeriesSpec("DFEDTARL", "Fed Funds Target Range Lower", "%", "D", "policy", up_signal="tightening", down_signal="easing", signal_change="3m", signal_threshold=0.10),
    # Real yields / breakevens
    SeriesSpec("DFII10", "10-Year TIPS Real Yield", "%", "D", "rates", up_signal="tightening", down_signal="easing", signal_threshold=0.15),
    SeriesSpec("T5YIE", "5-Year Breakeven Inflation", "%", "D", "inflation", up_signal="inflationary", down_signal="disinflationary", signal_threshold=0.10),
    SeriesSpec("T10YIE", "10-Year Breakeven Inflation", "%", "D", "inflation", up_signal="inflationary", down_signal="disinflationary", signal_threshold=0.10),
    # Inflation (YoY %)
    SeriesSpec("CPIAUCSL", "CPI (YoY)", "%", "M", "inflation", "yoy", "inflationary", "disinflationary", "3m", 0.20),
    SeriesSpec("CPILFESL", "Core CPI (YoY)", "%", "M", "inflation", "yoy", "inflationary", "disinflationary", "3m", 0.15),
    SeriesSpec("PCEPI", "PCE Price Index (YoY)", "%", "M", "inflation", "yoy", "inflationary", "disinflationary", "3m", 0.20),
    SeriesSpec("PCEPILFE", "Core PCE Price Index (YoY)", "%", "M", "inflation", "yoy", "inflationary", "disinflationary", "3m", 0.15),
    # Labor
    SeriesSpec("UNRATE", "Unemployment Rate", "%", "M", "labor", up_signal="bearish_growth", down_signal="bullish_growth", signal_change="3m", signal_threshold=0.10),
    SeriesSpec("PAYEMS", "Nonfarm Payrolls (3m avg monthly change)", "thousands", "M", "labor", "diff_3m_avg", "bullish_growth", "bearish_growth", "3m", 50.0),
    SeriesSpec("ICSA", "Initial Jobless Claims", "claims", "W", "labor", up_signal="bearish_growth", down_signal="bullish_growth", signal_change="1m", signal_threshold=15000.0),
    SeriesSpec("CCSA", "Continuing Jobless Claims", "claims", "W", "labor", up_signal="bearish_growth", down_signal="bullish_growth", signal_change="1m", signal_threshold=50000.0),
    SeriesSpec("SAHMREALTIME", "Sahm Rule Recession Indicator (real-time)", "pp", "M", "labor", up_signal="bearish_growth", down_signal="bullish_growth", signal_change="3m", signal_threshold=0.10),
    # Growth (YoY %)
    SeriesSpec("GDPC1", "Real GDP (YoY)", "%", "Q", "growth", "yoy", "bullish_growth", "bearish_growth", "1q", 0.30),
    # CBO trend estimates (published with projections years ahead; truncated to as_of)
    SeriesSpec("GDPPOT", "CBO Real Potential GDP (YoY)", "%", "Q", "growth", "yoy"),
    SeriesSpec("NROU", "CBO Noncyclical Rate of Unemployment", "%", "Q", "labor"),
    SeriesSpec("INDPRO", "Industrial Production (YoY)", "%", "M", "growth", "yoy", "bullish_growth", "bearish_growth", "3m", 0.50),
    SeriesSpec("RSAFS", "Retail Sales, nominal (YoY)", "%", "M", "growth", "yoy", "bullish_growth", "bearish_growth", "3m", 0.75),
    SeriesSpec("PI", "Personal Income (YoY)", "%", "M", "growth", "yoy", "bullish_growth", "bearish_growth", "3m", 0.50),
    SeriesSpec("DSPIC96", "Real Disposable Personal Income (YoY)", "%", "M", "growth", "yoy", "bullish_growth", "bearish_growth", "3m", 0.50),
    # Housing (leading)
    SeriesSpec("HOUST", "Housing Starts", "thousands (SAAR)", "M", "housing", up_signal="bullish_growth", down_signal="bearish_growth", signal_change="3m", signal_threshold=50.0),
    SeriesSpec("PERMIT", "Building Permits", "thousands (SAAR)", "M", "housing", up_signal="bullish_growth", down_signal="bearish_growth", signal_change="3m", signal_threshold=50.0),
    # Credit
    SeriesSpec("BAMLH0A0HYM2", "US High Yield OAS", "%", "D", "credit", up_signal="tightening", down_signal="easing", signal_change="1m", signal_threshold=0.25),
    SeriesSpec("BAMLC0A0CM", "US Investment Grade OAS", "%", "D", "credit", up_signal="tightening", down_signal="easing", signal_change="1m", signal_threshold=0.10),
    # Long-history credit spread (daily from 1986) - the ICE BofA OAS series above
    # are licensed to FRED for ~3 years only, too short for 10y statistics.
    SeriesSpec("BAA10Y", "Moody's Baa Corporate Spread over 10Y Treasury", "pp", "D", "credit", up_signal="tightening", down_signal="easing", signal_change="1m", signal_threshold=0.15),
    # Financial conditions
    SeriesSpec("NFCI", "Chicago Fed National Financial Conditions Index", "index", "W", "financial_conditions", up_signal="tightening", down_signal="easing", signal_change="1m", signal_threshold=0.05),
    SeriesSpec("STLFSI4", "St. Louis Fed Financial Stress Index", "index", "W", "financial_conditions", up_signal="tightening", down_signal="easing", signal_change="1m", signal_threshold=0.20),
    # Volatility / sentiment
    SeriesSpec("VIXCLS", "CBOE Volatility Index (VIX)", "index", "D", "volatility", up_signal="tightening", down_signal="easing", signal_change="1w", signal_threshold=3.0),
    SeriesSpec("UMCSENT", "UMich Consumer Sentiment", "index", "M", "sentiment", up_signal="bullish_growth", down_signal="bearish_growth", signal_change="3m", signal_threshold=3.0),
    # Recession reference - backtesting only, never reported as a live indicator
    SeriesSpec("USREC", "NBER Recession Indicator", "binary", "M", "reference", backtest_only=True),
)

SERIES_BY_REGION: dict[str, tuple[SeriesSpec, ...]] = {"US": US_SERIES}

FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{series_id}"

# How far back to fetch, per frequency. Daily series only need enough for
# 10y z-scores/percentiles; slower series fetch more so "highest since"
# lookbacks and backtest-style composites have a long history.
HISTORY_YEARS: dict[str, int] = {"D": 25, "W": 35, "M": 50, "Q": 50}

# A series is stale if its last observation is older than one period plus
# this grace (calendar days) - monthly data routinely lands 2-6 weeks late.
STALENESS_GRACE_DAYS: dict[str, int] = {"D": 5, "W": 12, "M": 60, "Q": 120}
PERIOD_DAYS: dict[str, int] = {"D": 1, "W": 7, "M": 31, "Q": 92}

# Which changes to report per frequency (label -> calendar days back).
CHANGE_WINDOWS: dict[str, dict[str, int]] = {
    "D": {"1d": 1, "1w": 7, "1m": 30, "3m": 91, "1y": 365},
    "W": {"1w": 7, "1m": 30, "3m": 91, "1y": 365},
    "M": {"1m": 31, "3m": 92, "1y": 365},
    "Q": {"1q": 92, "1y": 365},
}


# --- Market watchlist (guide §3.2) ----------------------------------------

@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    name: str
    category: str
    unit: str = "USD"
    description: str = ""
    tags: tuple[str, ...] = ()


WATCHLIST: tuple[SymbolSpec, ...] = (
    SymbolSpec("SPY", "S&P 500 ETF", "equity_index"),
    SymbolSpec("QQQ", "Nasdaq-100 ETF", "equity_index"),
    SymbolSpec("IWM", "Russell 2000 ETF", "equity_index"),
    SymbolSpec("EFA", "Developed ex-US Equity ETF", "equity_index"),
    SymbolSpec("EEM", "Emerging Markets Equity ETF", "equity_index"),
    SymbolSpec("XLK", "Technology Sector ETF", "sector"),
    SymbolSpec("XLF", "Financials Sector ETF", "sector"),
    SymbolSpec("XLE", "Energy Sector ETF", "sector"),
    SymbolSpec("XLV", "Health Care Sector ETF", "sector"),
    SymbolSpec("XLY", "Consumer Discretionary Sector ETF", "sector"),
    SymbolSpec("XLP", "Consumer Staples Sector ETF", "sector"),
    SymbolSpec("XLI", "Industrials Sector ETF", "sector"),
    SymbolSpec("XLU", "Utilities Sector ETF", "sector"),
    SymbolSpec("XLB", "Materials Sector ETF", "sector"),
    SymbolSpec("XLRE", "Real Estate Sector ETF", "sector"),
    SymbolSpec("XLC", "Communication Services Sector ETF", "sector"),
    SymbolSpec("TLT", "20+ Year Treasury ETF", "rates_credit"),
    SymbolSpec("IEF", "7-10 Year Treasury ETF", "rates_credit"),
    SymbolSpec("HYG", "High Yield Corporate Bond ETF", "rates_credit"),
    SymbolSpec("LQD", "Investment Grade Corporate Bond ETF", "rates_credit"),
    SymbolSpec("DX-Y.NYB", "US Dollar Index", "macro_asset", "index"),
    SymbolSpec("CL=F", "WTI Crude Oil Futures", "macro_asset", "USD/bbl"),
    SymbolSpec("GLD", "Gold ETF", "macro_asset"),
    SymbolSpec("HG=F", "Copper Futures", "macro_asset", "USD/lb"),
    SymbolSpec("^VIX", "CBOE Volatility Index", "volatility", "index"),
)

PRICE_HISTORY_DAYS = 400  # enough for 52-week highs and 1y changes
PRICE_CHANGE_WINDOWS: dict[str, int] = {"1d": 1, "1w": 7, "1m": 30, "3m": 91, "1y": 365}
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"


# --- News (guide §3.3) ----------------------------------------------------

NEWS_QUERIES: tuple[str, ...] = (
    '"Treasury yields" OR "bond yields"',
    '"Federal Reserve" rate decision OR FOMC',
    "inflation CPI report",
    "jobs report payrolls",
    "recession fears economy",
    "oil prices OPEC",
    '"credit spreads" corporate bonds',
    "stock market today",
)
NEWS_RESULTS_PER_QUERY = 6
NEWS_TOP_N = 15
NEWS_TITLE_SIMILARITY = 0.85  # titles at least this similar are duplicates


# --- Query planner catalogs ------------------------------------------------
# The planner (planner.py) may add extras from these allowlists only - it
# never invents ids. Each entry is a full spec, so extras are fetched, cached
# and featurized by the same code as the core set. Extras are reported in
# planned_indicators / planned_market and never read by the regime or event
# rules. To add one: append a spec with a description and tags (tags are the
# planner's areas: rates, inflation, labor, growth, housing, credit, energy,
# equities, fx, global, fed, consumer).


def _extra(sid: str, name: str, unit: str, freq: Frequency, category: str, transform: Transform,
           tags: tuple[str, ...], description: str) -> SeriesSpec:
    return SeriesSpec(sid, name, unit, freq, category, transform, description=description, tags=tags)


EXTRA_SERIES_CATALOG: tuple[SeriesSpec, ...] = (
    # Energy & commodities
    _extra("DCOILWTICO", "WTI Crude Oil Spot", "USD/bbl", "D", "energy", "level", ("energy", "inflation"), "Daily WTI crude spot price"),
    _extra("DCOILBRENTEU", "Brent Crude Oil Spot", "USD/bbl", "D", "energy", "level", ("energy", "global"), "Daily Brent crude spot price"),
    _extra("GASREGW", "US Regular Gasoline Retail Price", "USD/gal", "W", "energy", "level", ("energy", "consumer", "inflation"), "Weekly average retail gasoline price"),
    _extra("CPIENGSL", "Energy CPI (YoY)", "%", "M", "inflation", "yoy", ("energy", "inflation"), "Energy component of CPI, year-over-year"),
    _extra("PPIACO", "PPI All Commodities (YoY)", "%", "M", "inflation", "yoy", ("inflation", "energy", "growth"), "Producer prices for all commodities, year-over-year"),
    # Inflation detail
    _extra("CUSR0000SAH1", "Shelter CPI (YoY)", "%", "M", "inflation", "yoy", ("inflation", "housing"), "Shelter component of CPI, year-over-year"),
    _extra("CUSR0000SASLE", "CPI Services less Energy (YoY)", "%", "M", "inflation", "yoy", ("inflation",), "Core services CPI, year-over-year"),
    _extra("CPIUFDSL", "Food CPI (YoY)", "%", "M", "inflation", "yoy", ("inflation", "consumer"), "Food component of CPI, year-over-year"),
    _extra("MICH", "UMich 1-Year Inflation Expectations", "%", "M", "inflation", "level", ("inflation", "consumer"), "Median expected inflation over the next year (survey)"),
    # Labor detail
    _extra("JTSJOL", "JOLTS Job Openings", "thousands", "M", "labor", "level", ("labor",), "Total nonfarm job openings"),
    _extra("CES0500000003", "Average Hourly Earnings (YoY)", "%", "M", "labor", "yoy", ("labor", "inflation"), "Private average hourly earnings, year-over-year"),
    _extra("CIVPART", "Labor Force Participation Rate", "%", "M", "labor", "level", ("labor",), "Civilian labor force participation"),
    _extra("U6RATE", "U-6 Unemployment Rate", "%", "M", "labor", "level", ("labor",), "Broad unemployment incl. part-time for economic reasons"),
    # Housing & consumer
    _extra("MORTGAGE30US", "30-Year Fixed Mortgage Rate", "%", "W", "housing", "level", ("housing", "rates", "consumer"), "Freddie Mac weekly 30-year mortgage rate"),
    _extra("CSUSHPINSA", "Case-Shiller US Home Price Index (YoY)", "%", "M", "housing", "yoy", ("housing",), "National home prices, year-over-year"),
    _extra("HSN1F", "New Home Sales", "thousands (SAAR)", "M", "housing", "level", ("housing", "growth"), "New single-family homes sold"),
    _extra("TOTALSL", "Consumer Credit Outstanding (YoY)", "%", "M", "consumer", "yoy", ("consumer", "credit"), "Total consumer credit, year-over-year"),
    _extra("DRCCLACBS", "Credit Card Delinquency Rate", "%", "Q", "consumer", "level", ("consumer", "credit"), "Delinquency rate on credit card loans, all banks"),
    # Business / output
    _extra("TCU", "Capacity Utilization", "%", "M", "growth", "level", ("growth",), "Total industry capacity utilization"),
    _extra("DGORDER", "Durable Goods Orders (YoY)", "%", "M", "growth", "yoy", ("growth",), "Manufacturers' new orders for durable goods, year-over-year"),
    _extra("BUSINV", "Business Inventories (YoY)", "%", "M", "growth", "yoy", ("growth",), "Total business inventories, year-over-year"),
    # Rates detail
    _extra("DGS5", "5-Year Treasury Yield", "%", "D", "rates", "level", ("rates",), "5-year constant-maturity Treasury yield"),
    _extra("DGS1", "1-Year Treasury Yield", "%", "D", "rates", "level", ("rates", "fed"), "1-year constant-maturity Treasury yield"),
    _extra("SOFR", "Secured Overnight Financing Rate", "%", "D", "policy", "level", ("rates", "fed"), "Overnight repo funding rate"),
    _extra("WALCL", "Fed Balance Sheet Total Assets (YoY)", "%", "W", "policy", "yoy", ("fed", "rates"), "Federal Reserve total assets, year-over-year (QT/QE)"),
    _extra("RRPONTSYD", "Fed Overnight Reverse Repo", "USD bn", "D", "policy", "level", ("fed", "rates"), "Overnight reverse repurchase agreements (liquidity)"),
    # Global / FX
    _extra("DTWEXBGS", "Broad Trade-Weighted Dollar Index", "index", "D", "fx", "level", ("fx", "global"), "Nominal broad US dollar index"),
    _extra("DEXJPUS", "Japanese Yen per US Dollar", "JPY/USD", "D", "fx", "level", ("fx", "global"), "USD/JPY exchange rate"),
    _extra("DEXCHUS", "Chinese Yuan per US Dollar", "CNY/USD", "D", "fx", "level", ("fx", "global"), "USD/CNY exchange rate"),
    _extra("DEXUSEU", "US Dollars per Euro", "USD/EUR", "D", "fx", "level", ("fx", "global"), "EUR/USD exchange rate"),
    _extra("IRLTLT01DEM156N", "Germany 10-Year Government Bond Yield", "%", "M", "global", "level", ("global", "rates"), "German long-term government bond yield (monthly)"),
    _extra("IRLTLT01JPM156N", "Japan 10-Year Government Bond Yield", "%", "M", "global", "level", ("global", "rates"), "Japanese long-term government bond yield (monthly)"),
    # Credit detail
    _extra("BAMLH0A3HYC", "US CCC & Lower High Yield OAS", "%", "D", "credit", "level", ("credit",), "ICE BofA CCC-and-lower option-adjusted spread"),
    _extra("BAMLC0A4CBBB", "US BBB Corporate OAS", "%", "D", "credit", "level", ("credit",), "ICE BofA BBB option-adjusted spread"),
    _extra("DRTSCILM", "SLOOS: Banks Tightening C&I Loan Standards", "% net", "Q", "credit", "level", ("credit", "growth"), "Net share of banks tightening lending standards for large/mid firms"),
)

EXTRA_SYMBOL_CATALOG: tuple[SymbolSpec, ...] = (
    # Industry ETFs
    SymbolSpec("SMH", "Semiconductor ETF", "industry", description="US-listed semiconductor stocks", tags=("equities", "growth")),
    SymbolSpec("KRE", "Regional Banks ETF", "industry", description="US regional bank stocks", tags=("equities", "credit")),
    SymbolSpec("XHB", "Homebuilders ETF (SPDR)", "industry", description="Homebuilders and building products", tags=("housing", "equities")),
    SymbolSpec("ITB", "Home Construction ETF (iShares)", "industry", description="US home construction stocks", tags=("housing", "equities")),
    SymbolSpec("XOP", "Oil & Gas E&P ETF", "industry", description="Oil and gas exploration and production stocks", tags=("energy", "equities")),
    SymbolSpec("XRT", "Retail ETF", "industry", description="US retail stocks", tags=("consumer", "equities")),
    SymbolSpec("IYT", "Transportation ETF", "industry", description="US transportation stocks (cyclical bellwether)", tags=("growth", "equities")),
    SymbolSpec("JETS", "Airlines ETF", "industry", description="Global airline stocks (fuel-cost sensitive)", tags=("energy", "consumer", "equities")),
    # Factors / style
    SymbolSpec("MTUM", "Momentum Factor ETF", "factor", description="US momentum factor", tags=("equities",)),
    SymbolSpec("QUAL", "Quality Factor ETF", "factor", description="US quality factor", tags=("equities",)),
    SymbolSpec("USMV", "Min Volatility ETF", "factor", description="US minimum-volatility stocks (defensive)", tags=("equities",)),
    SymbolSpec("RSP", "Equal-Weight S&P 500 ETF", "factor", description="Equal-weight S&P 500 (market breadth)", tags=("equities",)),
    # International
    SymbolSpec("FXI", "China Large-Cap ETF", "international", description="Chinese large-cap stocks", tags=("global", "equities")),
    SymbolSpec("EWJ", "Japan ETF", "international", description="Japanese stocks", tags=("global", "equities", "fx")),
    SymbolSpec("EWG", "Germany ETF", "international", description="German stocks", tags=("global", "equities")),
    SymbolSpec("EWS", "Singapore ETF", "international", description="Singapore stocks", tags=("global", "equities")),
    SymbolSpec("INDA", "India ETF", "international", description="Indian stocks", tags=("global", "equities")),
    # Rates / credit
    SymbolSpec("SHY", "1-3 Year Treasury ETF", "rates_credit", description="Short-dated Treasuries (Fed-path sensitive)", tags=("rates", "fed")),
    SymbolSpec("TIP", "TIPS ETF", "rates_credit", description="Inflation-protected Treasuries", tags=("inflation", "rates")),
    SymbolSpec("BKLN", "Senior Loan ETF", "rates_credit", description="Leveraged loans", tags=("credit",)),
    SymbolSpec("EMB", "EM USD Bond ETF", "rates_credit", description="Emerging-market dollar sovereign bonds", tags=("credit", "global")),
    # Commodities / FX
    SymbolSpec("BZ=F", "Brent Crude Futures", "macro_asset", "USD/bbl", description="Front-month Brent crude futures", tags=("energy", "global")),
    SymbolSpec("NG=F", "Natural Gas Futures", "macro_asset", "USD/MMBtu", description="Front-month Henry Hub natural gas futures", tags=("energy",)),
    SymbolSpec("SLV", "Silver ETF", "macro_asset", description="Silver bullion", tags=("inflation",)),
    SymbolSpec("FXY", "Japanese Yen ETF", "macro_asset", description="Yen vs US dollar", tags=("fx", "global")),
    SymbolSpec("BTC-USD", "Bitcoin", "macro_asset", description="Bitcoin in US dollars (risk appetite)", tags=("equities",)),
)

PLANNER_MAX_EXTRA_SERIES = 8
PLANNER_MAX_EXTRA_SYMBOLS = 8
PLANNER_MAX_NEWS_QUERIES = 4
PLANNER_TIMEOUT_S = 8.0
PLANNER_HEURISTIC_PICKS = 3

# Heuristic fallback: keyword (word-prefix match on query + focus) -> catalog tag.
PLANNER_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "energy": ("oil", "crude", "opec", "brent", "wti", "gasoline", "energy", "natural gas", "natgas"),
    "housing": ("housing", "mortgage", "home", "homebuilder", "real estate", "rent"),
    "labor": ("labor", "labour", "job", "employment", "unemployment", "payroll", "wage", "hiring", "layoff"),
    "inflation": ("inflation", "cpi", "pce", "prices", "shelter"),
    "rates": ("yield", "treasury", "treasuries", "rates", "bond", "duration", "curve"),
    "fed": ("fed", "federal reserve", "fomc", "powell", "balance sheet", "repo"),
    "credit": ("credit", "spread", "high yield", "junk", "default", "loan", "bank"),
    "fx": ("dollar", "yen", "euro", "currency", "fx", "yuan"),
    "global": ("china", "japan", "europe", "germany", "emerging", "global", "india", "singapore"),
    "equities": ("stock", "equity", "equities", "s&p", "nasdaq", "sector", "semiconductor", "tech"),
    "consumer": ("consumer", "retail", "spending", "delinquen"),
    "growth": ("growth", "gdp", "recession", "manufacturing", "industrial", "output"),
}


# --- Event explanations -----------------------------------------------------

@dataclass(frozen=True)
class EventExplainSpec:
    """How event_explainer.py investigates one kind of event.

    `query_templates` may use {direction} (from the sign of the first evidence
    series' change, worded by `direction_words` = (positive, negative)) and
    {month_year} (the evidence's latest observation month). `topics` are
    news_tagging keyword topics used to reuse already-fetched news.
    """
    context_series: tuple[str, ...]
    context_symbols: tuple[str, ...]
    query_templates: tuple[str, ...]
    lookback_days: int
    decomposition: Optional[str] = None
    topics: tuple[str, ...] = ()
    direction_words: tuple[str, str] = ("rises", "falls")


_YIELD_EXPLAIN = EventExplainSpec(
    ("DGS2", "DGS30", "DFII10", "T10YIE", "DFF", "T10Y2Y"), ("TLT",),
    ('"10-year Treasury yield" {direction} why', "Treasury selloff term premium supply"),
    10, "yield_real_vs_breakeven", ("rates", "fed"),
)
_CURVE_EXPLAIN = EventExplainSpec(
    ("DGS3MO", "DGS2", "DGS10", "DFF"), (),
    ("yield curve {direction} Treasury", "bear steepening OR bull steepening"),
    14, "curve_front_vs_back", ("rates", "fed"), ("steepens", "inverts"),
)
_LABOR_EXPLAIN = EventExplainSpec(
    ("UNRATE", "PAYEMS", "ICSA", "CCSA"), (),
    ("jobless claims layoffs", "unemployment rate rises"),
    21, None, ("labor",),
)
_EQUITY_EXPLAIN = EventExplainSpec(
    ("VIXCLS", "BAMLH0A0HYM2", "DGS10"), ("SPY", "QQQ", "^VIX"),
    ("stock market selloff why", "S&P 500 correction"),
    7, None, ("equities",),
)

# Keyed by event-id prefix (events.py); the longest matching prefix wins.
EVENT_EXPLAIN_SPECS: dict[str, EventExplainSpec] = {
    "dgs10_": _YIELD_EXPLAIN,
    "dgs30_": _YIELD_EXPLAIN,
    "t10y3m_": _CURVE_EXPLAIN,
    "t10y2y_": _CURVE_EXPLAIN,
    "sahm_rule": _LABOR_EXPLAIN,
    "jobless_claims": _LABOR_EXPLAIN,
    "credit_stress": EventExplainSpec(
        ("BAMLH0A0HYM2", "BAMLC0A0CM", "VIXCLS"), ("HYG", "LQD"),
        ("high yield spreads widen", "corporate bond selloff defaults"), 14, None, ("credit",),
    ),
    "financial_conditions": EventExplainSpec(
        ("NFCI", "STLFSI4", "VIXCLS", "BAMLH0A0HYM2"), (),
        ("financial conditions tighten markets",), 14, None, ("credit", "equities"),
    ),
    "core_inflation": EventExplainSpec(
        ("CPILFESL", "CPIAUCSL", "PCEPILFE", "T5YIE"), (),
        ("core inflation CPI {month_year} shelter services", "CPI report hotter than expected"),
        30, "core_cpi_momentum", ("inflation",),
    ),
    "spy_": _EQUITY_EXPLAIN,
    "volatility_spike": _EQUITY_EXPLAIN,
    "oil_shock": EventExplainSpec(
        ("T5YIE",), ("CL=F", "XLE"), ("oil prices surge OPEC supply", "crude oil rally"), 14, None, ("energy",),
    ),
    "fed_": EventExplainSpec(
        ("DFF", "DGS2", "T10Y2Y"), (), ("Fed raises OR cuts rates FOMC statement",), 60, None, ("fed",),
    ),
}

EXPLAIN_MAX_EVENTS = 4
EXPLAIN_MAX_ARTICLES = 5
EXPLAIN_TIMEOUT_S = 20.0
EXPLAIN_MIN_BUDGET_S = 8.0
EXPLAIN_SNIPPET_CHARS = 300
EXPLAIN_MAX_WORDS = 70


# --- Output quality gate (quality.py) --------------------------------------
# A run is "degraded" if any of these is missing or stale, "unusable" if there
# are no FRED indicators or no regime phase at all.
QUALITY_KEY_INDICATORS: tuple[str, ...] = ("DGS10", "T10Y3M", "UNRATE", "CPILFESL", "PAYEMS")
QUALITY_KEY_SYMBOLS: tuple[str, ...] = ("SPY",)
QUALITY_PROBABILITY_TOLERANCE = 0.01


# --- Cache TTLs (seconds) -------------------------------------------------

SERIES_TTL_SECONDS: dict[str, int] = {"D": 3600, "W": 6 * 3600, "M": 12 * 3600, "Q": 12 * 3600}
QUOTE_TTL_SECONDS = 300
NEWS_TTL_SECONDS = 900
HISTORICAL_TTL_SECONDS = 7 * 24 * 3600  # data for a past as_of doesn't change


# --- Notable-event thresholds (guide §4.2) --------------------------------

@dataclass(frozen=True)
class EventThresholds:
    yield_high_min_years: float = 2.0       # report "highest since" only past this lookback
    yield_high_major_years: float = 10.0
    yield_move_1w: float = 0.25             # pp
    yield_move_1m: float = 0.50             # pp
    curve_cross_window_days: int = 30
    long_inversion_days: int = 180          # un-inversion after this long inverted is "major"
    sahm_trigger: float = 0.50
    sahm_warning: float = 0.30
    claims_rise_from_low: float = 0.15      # 4wk avg vs 52-week low of the 4wk avg
    hy_oas_3m_widening: float = 1.00        # pp, ICE BofA HY OAS (short history - changes only)
    credit_spread_3m_widening: float = 0.50 # pp, Baa-Treasury spread (BAA10Y)
    credit_high_percentile: float = 80.0    # BAA10Y vs its last 10 years
    nfci_tight_level: float = 0.0
    nfci_3m_rise: float = 0.20
    inflation_reaccel_gap: float = 0.50     # core 3m annualized minus core YoY, pp
    equity_correction: float = 0.10
    equity_bear: float = 0.20
    vix_spike_level: float = 30.0
    vix_spike_1w_rise: float = 0.50
    oil_shock_3m_rise: float = 0.25
    policy_change_window_days: int = 60


EVENT_THRESHOLDS = EventThresholds()


# --- Recession probability (guide §4.3) -----------------------------------
# NY Fed "Yield Curve as a Leading Indicator" probit:
#   P(recession in 12m) = Phi(alpha + beta * spread_10y_3m)
# Coefficients as published by the NY Fed (verify periodically). The NY Fed
# uses the monthly average 10y-3m spread on a bond-equivalent basis;
# FRED's T10Y3M (constant-maturity) is a close approximation.
PROBIT_ALPHA = -0.5333
PROBIT_BETA = -0.6330
PROBIT_AVERAGE_DAYS = 30


# --- Cycle phase classifier (guide §4.4) ----------------------------------

PHASES = ("early_expansion", "late_expansion", "recession", "late_recession")


@dataclass(frozen=True)
class RegimeConfig:
    zscore_years: int = 10
    # Walk-forward (tuned on 1980-2005 only): momentum 9, adjustments 0.5/0.5, temperature 1.0.
    momentum_months: int = 9

    # Growth level G: component -> weight. Signs are applied in regime.py
    # (unemployment gap and claims trend are inverted).
    growth_weights: dict[str, float] = field(default_factory=lambda: {
        "INDPRO_YOY": 1.0,
        "REAL_RETAIL_YOY": 0.75,
        "PAYEMS_3M_AVG": 1.0,
        "GDPC1_YOY": 0.75,
        "UNRATE_GAP": 1.25,
        "ICSA_TREND": 1.0,
        "UNRATE_NROU_GAP": 0.0,
        "OUTPUT_GAP": 0.0,
    })
    # Trend-gap components are scaled (gap / scale), not z-scored vs 10 years.
    trend_gap_scales: dict[str, float] = field(default_factory=lambda: {
        "UNRATE_NROU_GAP": 1.0,   # pp of unemployment above the CBO natural rate
        "OUTPUT_GAP": 2.0,        # % below CBO potential GDP
    })

    # Inflation pressure I: (value - anchor) / scale, averaged.
    inflation_anchors: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "CPILFESL_YOY": (2.0, 1.0),
        "PCEPILFE_YOY": (2.0, 1.0),
        "CPILFESL_3M_ANN": (2.0, 1.5),
        "T5YIE": (2.25, 0.35),
    })

    # Policy / financial stance P (positive = restrictive / tight).
    neutral_real_rate: float = 0.5
    real_rate_scale: float = 1.0
    curve_scale: float = 1.0
    policy_weights: dict[str, float] = field(default_factory=lambda: {
        "REAL_POLICY_RATE": 1.0,
        "CURVE_FLATNESS": 0.75,
        "CREDIT_SPREAD": 1.0,
        "NFCI": 1.0,
    })
    # Credit spread used by P and the credit adjustments: needs long history for
    # 10y z-scores/percentiles (ICE BofA HY OAS has only ~3 years on FRED).
    credit_series: str = "BAA10Y"

    # Base quadrant score = base_scale * (sG*G + sM*M), so the argmax of the
    # base scores is exactly the guide's growth/momentum quadrant.
    base_scale: float = 1.0
    momentum_weight: float = 1.0

    # Confirmation adjustments (guide step 3) - each fired condition adds
    # this much to its phase's score.
    adjustment_weight: float = 0.50
    strong_adjustment_weight: float = 0.50   # Sahm rule, payrolls negative

    # Thresholds used by the adjustments.
    unrate_near_low_gap: float = 0.25
    unrate_high_percentile: float = 60.0
    curve_flat: float = 0.25
    curve_steep: float = 1.0
    easing_6m: float = -0.25
    aggressive_easing_6m: float = -1.0
    tightening_6m: float = 0.25
    credit_tight_percentile: float = 35.0
    credit_wide_percentile: float = 70.0
    credit_blowout_3m: float = 0.50          # pp widening in 3 months
    probit_high: float = 0.5
    claims_surge: float = 0.20
    equity_rally_off_low: float = 0.15
    inflation_elevated: float = 0.5
    policy_restrictive: float = 0.5

    # Softmax / confidence / hysteresis (guide steps 4-5).
    temperature: float = 1.0
    confidence_medium: float = 0.15
    confidence_high: float = 0.35
    hysteresis_margin: float = 0.10
    # EMA weight on the new month's scores (1.0 = no smoothing).
    score_smoothing: float = 1.0
    # (a, b) of P = sigmoid(a + b * logit(raw P(in recession))), fitted on
    # 1980-2005 by `backtest --walk-forward`. None = uncalibrated.
    calibration: Optional[tuple[float, float]] = None
    top_drivers: int = 5
    conflict_threshold: float = 0.25

    # Adjustment ids (regime.ADJUSTMENT_IDS) to switch off - for backtest ablations.
    disabled_adjustments: tuple[str, ...] = ()


REGIME_CONFIG = RegimeConfig()


# --- Runtime settings (env-driven) ----------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = _BACKEND_DIR / "data" / "market_research"


@dataclass(frozen=True)
class Settings:
    fred_api_key: Optional[str]
    tavily_api_key: Optional[str]
    market_data_provider: str
    news_provider: str
    output_dir: Path
    api_token: Optional[str]
    max_concurrent_runs: int
    max_queued_runs: int
    source_timeout_seconds: float
    request_timeout_seconds: float
    run_budget_seconds: float


def load_settings() -> Settings:
    return Settings(
        fred_api_key=os.getenv("FRED_API_KEY") or None,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
        market_data_provider=os.getenv("MARKET_DATA_PROVIDER", "yfinance"),
        news_provider=os.getenv("NEWS_PROVIDER", "tavily"),
        output_dir=Path(os.getenv("MARKET_RESEARCH_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR),
        api_token=os.getenv("MARKET_RESEARCH_API_TOKEN") or None,
        max_concurrent_runs=int(os.getenv("MARKET_RESEARCH_MAX_CONCURRENT_RUNS", "2")),
        max_queued_runs=int(os.getenv("MARKET_RESEARCH_MAX_QUEUED_RUNS", "8")),
        source_timeout_seconds=float(os.getenv("MARKET_RESEARCH_SOURCE_TIMEOUT", "45")),
        request_timeout_seconds=float(os.getenv("MARKET_RESEARCH_REQUEST_TIMEOUT", "10")),
        run_budget_seconds=float(os.getenv("MARKET_RESEARCH_RUN_BUDGET", "90")),
    )
