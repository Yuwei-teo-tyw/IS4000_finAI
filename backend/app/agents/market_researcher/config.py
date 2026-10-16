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

SCHEMA_VERSION = "1.0"
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
    hy_oas_3m_widening: float = 1.00        # pp
    hy_oas_high_percentile: float = 80.0
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
    momentum_months: int = 6  # backtest: 3m momentum produced 5 false recession calls vs 2 at 6m

    # Growth level G: component -> weight. Signs are applied in regime.py
    # (unemployment gap and claims trend are inverted).
    growth_weights: dict[str, float] = field(default_factory=lambda: {
        "INDPRO_YOY": 1.0,
        "REAL_RETAIL_YOY": 0.75,
        "PAYEMS_3M_AVG": 1.0,
        "GDPC1_YOY": 0.75,
        "UNRATE_GAP": 1.25,
        "ICSA_TREND": 1.0,
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
        "HY_OAS": 1.0,
        "NFCI": 1.0,
    })

    # Base quadrant score = base_scale * (sG*G + sM*M), so the argmax of the
    # base scores is exactly the guide's growth/momentum quadrant.
    base_scale: float = 1.0
    momentum_weight: float = 1.0

    # Confirmation adjustments (guide step 3) - each fired condition adds
    # this much to its phase's score.
    adjustment_weight: float = 0.35
    strong_adjustment_weight: float = 0.75   # Sahm rule, payrolls negative

    # Thresholds used by the adjustments.
    unrate_near_low_gap: float = 0.25
    unrate_high_percentile: float = 60.0
    curve_flat: float = 0.25
    curve_steep: float = 1.0
    easing_6m: float = -0.25
    aggressive_easing_6m: float = -1.0
    tightening_6m: float = 0.25
    hy_tight_percentile: float = 35.0
    hy_wide_percentile: float = 70.0
    probit_high: float = 0.5
    claims_surge: float = 0.20
    equity_rally_off_low: float = 0.15
    inflation_elevated: float = 0.5
    policy_restrictive: float = 0.5

    # Softmax / confidence / hysteresis (guide steps 4-5).
    temperature: float = 0.6
    confidence_medium: float = 0.15
    confidence_high: float = 0.35
    hysteresis_margin: float = 0.10
    top_drivers: int = 5
    conflict_threshold: float = 0.25


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
        run_budget_seconds=float(os.getenv("MARKET_RESEARCH_RUN_BUDGET", "60")),
    )
