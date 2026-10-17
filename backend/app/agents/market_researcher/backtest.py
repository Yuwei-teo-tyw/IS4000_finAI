"""
Regime classifier backtest vs NBER recession dates (guide §4.5).

    cd backend && python -m app.agents.market_researcher.backtest [--start 1980-01-01] [--out PATH]
                                                                  [--walk-forward] [--ablation] [--workers N]

Runs `classify_regime` monthly (with hysteresis, as live) and compares the
calls to FRED's USREC. Writes a Markdown report (default:
backtest_report.md next to this file).

**Same model as live.** The backtest feeds the classifier the same inputs it
gets in production:
- credit: Moody's Baa-Treasury spread (BAA10Y, daily from 1986; monthly
  BAA - GS10 spliced in before that). The ICE BofA OAS series FRED serves
  only ~3 years, so the model doesn't use them.
- equities: S&P 500 index (^GSPC via yfinance) standing in for SPY - the one
  rule that reads prices ("equities rallying off their lows") is ratio-based,
  so the index and the ETF behave the same.
- curve: daily T10Y3M, monthly GS10 - TB3MS before 1982.

**Measured against baselines.** The same scoring is applied to simple
rules (Sahm rule, yield-curve probit, either) so the composite has to earn
its complexity.

**Optional:**
- `--walk-forward` tunes a small grid of knobs on 1980-2005 only and
  scores the chosen config on 2006 onward (the honest out-of-sample number).
- `--ablation` switches off one component or adjustment at a time.

Look-ahead bias: uses *revised* FRED data, not ALFRED vintages (a vintage
fetch per month would be ~10k API calls). To limit the bias each series is
only visible after a per-frequency publication lag (PUBLICATION_LAG_DAYS),
so e.g. September CPI is first used in mid-October. Revisions to activity
data (payrolls, GDP, IP) still make this somewhat optimistic.

Tune weights/thresholds in config.RegimeConfig, never in code.
"""
import argparse
import asyncio
import dataclasses
import itertools
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from typing import Optional

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.adapters.fred import FredClient
from app.agents.market_researcher.config import PHASES, REGIME_CONFIG, RegimeConfig
from app.agents.market_researcher.regime import ADJUSTMENT_IDS, classify_regime, recession_probability

BACKTEST_SERIES = {
    # id: frequency
    "INDPRO": "M", "RSAFS": "M", "CPIAUCSL": "M", "PAYEMS": "M", "GDPC1": "Q",
    "UNRATE": "M", "ICSA": "W", "CPILFESL": "M", "PCEPILFE": "M", "T5YIE": "D",
    "DFF": "D", "T10Y3M": "D", "GS10": "M", "TB3MS": "M", "BAA10Y": "D", "BAA": "M",
    "NFCI": "W", "SAHMREALTIME": "M", "PERMIT": "M", "UMCSENT": "M", "USREC": "M",
    "NROU": "Q", "GDPPOT": "Q",
}
SPLICE_ONLY = ("GS10", "TB3MS", "BAA")   # only used to extend T10Y3M / BAA10Y back in time
PUBLICATION_LAG_DAYS = {"D": 1, "W": 7, "M": 45, "Q": 90}
FETCH_START = date(1965, 1, 1)
EQUITY_PROXY = "^GSPC"   # S&P 500 index, fed to the model as "SPY"

DEFAULT_REPORT_PATH = Path(__file__).parent / "backtest_report.md"

# Acceptance (guide §4.5): catch most NBER recessions, few sustained false calls.
MIN_CATCH_SHARE = 0.6
MAX_FALSE_CALLS = 3
CATCH_WINDOW_MONTHS = 3        # a recession call within [start-3m, end+3m] counts
FALSE_CALL_BUFFER_MONTHS = 6   # recession calls this far outside NBER dates are false
FALSE_CALL_MIN_MONTHS = 3      # ...and count as a "sustained" false call if they last this long

# Walk-forward: tune on the train window only, score the test window.
TRAIN_WINDOW = (date(1980, 1, 1), date(2005, 12, 1))
TEST_START = date(2006, 1, 1)
WALK_FORWARD_GRID: dict[str, list] = {
    "growth_variant": ["zscore", "trend", "hybrid"],
    "score_smoothing": [1.0, 0.5, 0.3],
    "momentum_months": [6, 9],
    "hysteresis_margin": [0.10, 0.20],
    "adjustment_weight": [0.35, 0.50],
    "strong_adjustment_weight": [0.50, 0.75],
}

# Growth composite variants (grid key "growth_variant"):
#   zscore - every component z-scored vs its last 10 years (the original model)
#   trend  - unemployment and GDP measured as gaps vs CBO trend (NROU, GDPPOT)
#            instead of vs their own recent history
#   hybrid - both: the trend gaps added alongside the original components
_BASE_GROWTH = {"INDPRO_YOY": 1.0, "REAL_RETAIL_YOY": 0.75, "PAYEMS_3M_AVG": 1.0, "ICSA_TREND": 1.0}
GROWTH_VARIANTS: dict[str, dict[str, float]] = {
    "zscore": {**_BASE_GROWTH, "GDPC1_YOY": 0.75, "UNRATE_GAP": 1.25, "UNRATE_NROU_GAP": 0.0, "OUTPUT_GAP": 0.0},
    "trend": {**_BASE_GROWTH, "GDPC1_YOY": 0.0, "UNRATE_GAP": 0.0, "UNRATE_NROU_GAP": 1.25, "OUTPUT_GAP": 0.75},
    "hybrid": {**_BASE_GROWTH, "GDPC1_YOY": 0.75, "UNRATE_GAP": 1.25, "UNRATE_NROU_GAP": 1.0, "OUTPUT_GAP": 0.75},
}


def config_from(overrides: dict, base: RegimeConfig = REGIME_CONFIG) -> RegimeConfig:
    """RegimeConfig with overrides applied; `growth_variant` expands to growth_weights."""
    overrides = dict(overrides)
    variant = overrides.pop("growth_variant", None)
    if variant is not None:
        overrides["growth_weights"] = GROWTH_VARIANTS[variant]
    return dataclasses.replace(base, **overrides)


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _log_likelihood(a: float, b: float, pairs: list[tuple[float, int]], ridge: float) -> float:
    total = 0.0
    for x, y in pairs:
        p = min(max(_sigmoid(a + b * x), 1e-12), 1 - 1e-12)
        total += y * math.log(p) + (1 - y) * math.log(1 - p)
    return total - ridge * (a * a + b * b) / 2


def fit_calibration(probs: list[Optional[float]], outcomes: list[int], iterations: int = 100) -> tuple[float, float]:
    """Logistic regression of the NBER recession flag on logit(raw P(in recession)),
    by damped Newton's method (a small ridge keeps it finite if the classes
    separate): returns (a, b) for P = sigmoid(a + b * logit(p))."""
    pairs = [(_logit(p), y) for p, y in zip(probs, outcomes) if p is not None]
    a, b, ridge = 0.0, 1.0, 1e-2
    ll = _log_likelihood(a, b, pairs, ridge)
    for _ in range(iterations):
        ga, gb = ridge * a, ridge * b
        haa = hbb = ridge
        hab = 0.0
        for x, y in pairs:
            p = _sigmoid(a + b * x)
            w = p * (1 - p)
            ga += p - y
            gb += (p - y) * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        step = 1.0
        while step > 1e-6:
            na, nb = a - step * da, b - step * db
            nll = _log_likelihood(na, nb, pairs, ridge)
            if nll >= ll:
                break
            step /= 2
        if step <= 1e-6:
            break
        converged = abs(nll - ll) < 1e-10
        a, b, ll = na, nb, nll
        if converged:
            break
    return round(a, 4), round(b, 4)


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))

BASELINES = {
    "sahm": "Sahm rule (SAHMREALTIME >= 0.50)",
    "probit": "Yield-curve probit > 50%",
    "sahm_or_probit": "Sahm rule OR probit > 50%",
}


@dataclass
class Recession:
    start: date
    end: date
    caught: bool = False
    lead_months: Optional[int] = None       # first recession call relative to start (negative = early)
    late_expansion_before: bool = False     # late_expansion within 12m before start
    early_expansion_after: bool = False     # early_expansion within 12m after end


@dataclass
class BacktestResult:
    start: date
    end: date
    calls: list[tuple[date, Optional[str], int]] = field(default_factory=list)  # (month, phase, usrec)
    recessions: list[Recession] = field(default_factory=list)
    false_calls: list[tuple[date, date]] = field(default_factory=list)
    confusion: dict[str, dict[int, int]] = field(default_factory=dict)
    # P(in recession) = P(recession) + P(late_recession) per month, aligned with `calls`.
    recession_probs: list[Optional[float]] = field(default_factory=list)
    false_call_months: int = 0
    flips: int = 0
    baselines: dict[str, "BacktestResult"] = field(default_factory=dict)

    @property
    def caught(self) -> int:
        return sum(r.caught for r in self.recessions)

    @property
    def passed(self) -> bool:
        if not self.recessions:
            return False
        return self.caught >= math.ceil(MIN_CATCH_SHARE * len(self.recessions)) and len(self.false_calls) <= MAX_FALSE_CALLS

    @property
    def mean_lead(self) -> Optional[float]:
        leads = [r.lead_months for r in self.recessions if r.lead_months is not None]
        return fmean(leads) if leads else None

    @property
    def brier(self) -> Optional[float]:
        pairs = [(p, y) for p, (_, _, y) in zip(self.recession_probs, self.calls) if p is not None]
        return fmean((p - y) ** 2 for p, y in pairs) if pairs else None

    @property
    def brier_skill(self) -> Optional[float]:
        """1 - Brier / Brier of always forecasting the window's base rate.
        > 0 means the probabilities beat the base rate; <= 0 means they don't."""
        if self.brier is None or not self.calls:
            return None
        base = fmean(y for _, _, y in self.calls)
        climatology = base * (1 - base)
        return 1 - self.brier / climatology if climatology else None


async def fetch_history(fred: FredClient, end: date) -> dict[str, list[SeriesPoint]]:
    ids = list(BACKTEST_SERIES)
    results = await asyncio.gather(*(fred.get_series(s, FETCH_START, end) for s in ids), return_exceptions=True)
    history = {}
    for sid, res in zip(ids, results):
        if isinstance(res, Exception):
            print(f"backtest: could not fetch {sid}: {res}")
            continue
        history[sid] = res
    return history


def fetch_equity_history(start: date, end: date) -> dict[str, list[SeriesPoint]]:
    """S&P 500 daily closes, keyed "SPY" (the symbol the model reads). Empty on failure."""
    from app.agents.market_researcher.adapters.market_data import _download_closes

    try:
        closes = _download_closes([EQUITY_PROXY], start, end)
    except Exception as e:
        print(f"backtest: could not fetch {EQUITY_PROXY}: {type(e).__name__}: {e}")
        return {}
    return {"SPY": closes[EQUITY_PROXY]} if closes.get(EQUITY_PROXY) else {}


def _splice(monthly_older: list[SeriesPoint], daily: list[SeriesPoint]) -> list[SeriesPoint]:
    first = daily[0].date if daily else date.max
    return [p for p in monthly_older if p.date < first] + daily


def _monthly_diff(a: list[SeriesPoint], b: list[SeriesPoint]) -> list[SeriesPoint]:
    b_by_date = {p.date: p.value for p in b}
    return [SeriesPoint(p.date, p.value - b_by_date[p.date]) for p in a if p.date in b_by_date]


def splice_curve(history: dict[str, list[SeriesPoint]]) -> list[SeriesPoint]:
    """Daily T10Y3M where it exists, monthly GS10 - TB3MS before that."""
    return _splice(_monthly_diff(history.get("GS10") or [], history.get("TB3MS") or []), history.get("T10Y3M") or [])


def splice_credit(history: dict[str, list[SeriesPoint]]) -> list[SeriesPoint]:
    """Daily BAA10Y (from 1986) where it exists, monthly BAA - GS10 before that."""
    return _splice(_monthly_diff(history.get("BAA") or [], history.get("GS10") or []), history.get("BAA10Y") or [])


def prepare_history(history: dict[str, list[SeriesPoint]]) -> tuple[dict[str, list[SeriesPoint]], list[SeriesPoint]]:
    """(model inputs, USREC): splices the curve and credit spread back in time
    and drops the series only needed for splicing."""
    history = dict(history)
    history["T10Y3M"] = splice_curve(history)
    history["BAA10Y"] = splice_credit(history)
    usrec = history.pop("USREC", [])
    for sid in SPLICE_ONLY:
        history.pop(sid, None)
    return history, usrec


def visible_as_of(history: dict[str, list[SeriesPoint]], as_of: date) -> dict[str, list[SeriesPoint]]:
    out = {}
    for sid, pts in history.items():
        freq = BACKTEST_SERIES.get(sid, "D")
        out[sid] = f.truncate(pts, as_of - timedelta(days=PUBLICATION_LAG_DAYS[freq]))
    return out


def _months(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = f.shift_months(d, 1)
    return out


def nber_recessions(usrec: list[SeriesPoint], start: date, end: date) -> list[Recession]:
    recessions, current = [], None
    for p in usrec:
        if p.date < start or p.date > end:
            continue
        if p.value >= 0.5 and current is None:
            current = p.date
        elif p.value < 0.5 and current is not None:
            recessions.append(Recession(current, f.shift_months(p.date, -1)))
            current = None
    if current is not None:
        recessions.append(Recession(current, end))
    return recessions


def _month_diff(a: date, b: date) -> int:
    return (a.year - b.year) * 12 + (a.month - b.month)


def run_backtest(history: dict[str, list[SeriesPoint]], start: date, end: date,
                 cfg: RegimeConfig = REGIME_CONFIG, prices: Optional[dict[str, list[SeriesPoint]]] = None,
                 with_baselines: bool = False) -> BacktestResult:
    series, usrec = prepare_history(history)
    usrec_by_month = {p.date: int(p.value) for p in usrec}
    prices = prices or {}

    result = BacktestResult(start, end)
    baseline_calls: dict[str, list] = {k: [] for k in BASELINES}
    previous: Optional[dict] = None
    for month in _months(start, end):
        # Classify at the end of each month using only data published by then.
        as_of = f.shift_months(month, 1) - timedelta(days=1)
        visible = visible_as_of(series, as_of)
        visible_prices = {k: f.truncate(v, as_of - timedelta(days=1)) for k, v in prices.items()}
        regime = classify_regime(visible, as_of, previous=previous, prices=visible_prices, cfg=cfg)
        if regime.phase:
            previous = {"phase": regime.phase, "probabilities": regime.probabilities, "scores": regime.scores}
        rec = usrec_by_month.get(month, 0)
        result.calls.append((month, regime.phase, rec))
        result.recession_probs.append(regime.in_recession_prob)

        if with_baselines:
            sahm_pts = visible.get("SAHMREALTIME") or []
            sahm = bool(sahm_pts) and sahm_pts[-1].value >= 0.5
            probit = (recession_probability(visible, as_of) or 0) > 0.5
            for key, fired in (("sahm", sahm), ("probit", probit), ("sahm_or_probit", sahm or probit)):
                baseline_calls[key].append((month, "recession" if fired else "expansion", rec))

    result.recessions = nber_recessions(usrec, start, end)
    _score(result)
    if with_baselines:
        for key, calls in baseline_calls.items():
            b = BacktestResult(start, end, calls=calls, recessions=nber_recessions(usrec, start, end))
            _score(b)
            result.baselines[key] = b
    return result


def _score(result: BacktestResult) -> None:
    calls = {m: phase for m, phase, _ in result.calls}
    result.confusion = {phase: {0: 0, 1: 0} for phase in (*PHASES, "none")}
    for _, phase, rec in result.calls:
        result.confusion.setdefault(phase or "none", {0: 0, 1: 0})[rec] += 1

    for r in result.recessions:
        lo, hi = f.shift_months(r.start, -CATCH_WINDOW_MONTHS), f.shift_months(r.end, CATCH_WINDOW_MONTHS)
        hits = sorted(m for m, phase in calls.items() if lo <= m <= hi and phase == "recession")
        r.caught = bool(hits)
        r.lead_months = _month_diff(hits[0], r.start) if hits else None
        r.late_expansion_before = any(
            phase == "late_expansion" for m, phase in calls.items() if f.shift_months(r.start, -12) <= m < r.start
        )
        r.early_expansion_after = any(
            phase == "early_expansion" for m, phase in calls.items() if r.end < m <= f.shift_months(r.end, 12)
        )

    def near_recession(m: date) -> bool:
        return any(
            f.shift_months(r.start, -FALSE_CALL_BUFFER_MONTHS) <= m <= f.shift_months(r.end, FALSE_CALL_BUFFER_MONTHS)
            for r in result.recessions
        )

    result.false_calls, result.false_call_months = [], 0
    run: list[date] = []
    for m, phase, _ in result.calls + [(date.max, None, 0)]:
        if phase == "recession" and not near_recession(m):
            run.append(m)
            result.false_call_months += 1
            continue
        if len(run) >= FALSE_CALL_MIN_MONTHS:
            result.false_calls.append((run[0], run[-1]))
        run = []

    phases = [phase for _, phase, _ in result.calls if phase]
    result.flips = sum(1 for a, b in zip(phases, phases[1:]) if a != b)


# --- walk-forward and ablation (parallel) ----------------------------------------

_WORKER_DATA: dict = {}


def _init_worker(history, prices) -> None:
    _WORKER_DATA["history"], _WORKER_DATA["prices"] = history, prices


def summarize(result: BacktestResult, label: str = "") -> dict:
    return {
        "label": label,
        "caught": result.caught,
        "recessions": len(result.recessions),
        "sustained_false_calls": len(result.false_calls),
        "false_call_months": result.false_call_months,
        "flips": result.flips,
        "mean_lead": result.mean_lead,
        "brier_skill": result.brier_skill,
        "passed": result.passed,
    }


def _evaluate(args: tuple[str, dict, date, date]) -> dict:
    label, overrides, start, end = args
    result = run_backtest(_WORKER_DATA["history"], start, end, cfg=config_from(overrides), prices=_WORKER_DATA["prices"])
    return {**summarize(result, label), "overrides": overrides}


def _run_parallel(history, prices, tasks: list, workers: int) -> list[dict]:
    if workers <= 1:
        _init_worker(history, prices)
        return [_evaluate(t) for t in tasks]
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(history, prices)) as pool:
        return list(pool.map(_evaluate, tasks))


def objective(summary: dict) -> tuple:
    """Higher is better: catch share, then fewer sustained false calls, false-call months, flips."""
    share = summary["caught"] / summary["recessions"] if summary["recessions"] else 0.0
    return (share, -summary["sustained_false_calls"], -summary["false_call_months"], -summary["flips"])


@dataclass
class WalkForwardResult:
    best: dict                 # chosen on the train window
    train_default: dict
    test_tuned: dict           # the honest out-of-sample number (calibration fitted on train)
    test_default: dict         # current config on the test window (in-sample if the config was tuned on all data)
    grid_size: int
    calibration: tuple[float, float] = (0.0, 1.0)
    train_brier_skill_raw: Optional[float] = None
    train_brier_skill_calibrated: Optional[float] = None
    test_brier_skill_raw: Optional[float] = None


def walk_forward(history, prices, end: date, workers: int) -> WalkForwardResult:
    keys = list(WALK_FORWARD_GRID)
    combos = [dict(zip(keys, values)) for values in itertools.product(*WALK_FORWARD_GRID.values())]
    train_start, train_end = TRAIN_WINDOW
    train = _run_parallel(history, prices, [("grid", c, train_start, train_end) for c in combos]
                          + [("default", {}, train_start, train_end)], workers)
    train_default = train.pop()
    best = max(train, key=objective)

    # Calibrate the chosen config's P(in recession) on the train window only.
    uncalibrated = {**best["overrides"], "calibration": None}
    train_raw = run_backtest(history, train_start, train_end, cfg=config_from(uncalibrated), prices=prices)
    calibration = fit_calibration(train_raw.recession_probs, [y for _, _, y in train_raw.calls])
    tuned = {**best["overrides"], "calibration": calibration}
    train_cal = run_backtest(history, train_start, train_end, cfg=config_from(tuned), prices=prices)

    test_tuned, test_default, test_raw = _run_parallel(
        history, prices,
        [("tuned + calibrated on 1980-2005", tuned, TEST_START, end),
         ("current config", {}, TEST_START, end),
         ("tuned, uncalibrated", uncalibrated, TEST_START, end)],
        workers,
    )
    return WalkForwardResult(
        best, train_default, test_tuned, test_default, len(combos), calibration,
        train_raw.brier_skill, train_cal.brier_skill, test_raw["brier_skill"],
    )


def ablation_variants(cfg: RegimeConfig = REGIME_CONFIG) -> list[tuple[str, dict]]:
    variants: list[tuple[str, dict]] = [("current config", {})]
    for k in cfg.growth_weights:
        variants.append((f"growth: drop {k}", {"growth_weights": {**cfg.growth_weights, k: 0.0}}))
    for k in cfg.policy_weights:
        variants.append((f"policy: drop {k}", {"policy_weights": {**cfg.policy_weights, k: 0.0}}))
    for a in ADJUSTMENT_IDS:
        variants.append((f"adjustment: drop {a}", {"disabled_adjustments": (a,)}))
    variants.append(("no momentum (M = 0)", {"momentum_weight": 0.0}))
    variants.append(("no adjustments at all", {"disabled_adjustments": ADJUSTMENT_IDS}))
    return variants


def ablation(history, prices, start: date, end: date, workers: int) -> list[dict]:
    return _run_parallel(history, prices, [(label, o, start, end) for label, o in ablation_variants()], workers)


# --- report ---------------------------------------------------------------------

def _fmt(v, spec: str = "", none: str = "n/a") -> str:
    return none if v is None else format(v, spec)


def _summary_row(s: dict) -> str:
    return (f"| {s['label']} | {s['caught']}/{s['recessions']} | {_fmt(s['mean_lead'], '+.1f')} | "
            f"{s['sustained_false_calls']} | {s['false_call_months']} | {s['flips']} | {_fmt(s['brier_skill'], '+.2f')} |")


SUMMARY_HEADER = [
    "| Model | Recessions caught | Mean first call vs start (months) | Sustained false calls | False-call months | Phase changes | Brier skill |",
    "|---|---|---|---|---|---|---|",
]


def render_report(result: BacktestResult, equities_used: bool = True,
                  wf: Optional[WalkForwardResult] = None, ablations: Optional[list[dict]] = None) -> str:
    lines = [
        "# Regime classifier backtest",
        "",
        f"Window: {result.start} to {result.end}, monthly ({len(result.calls)} months). "
        "Generated by `python -m app.agents.market_researcher.backtest`.",
        "",
        "**Inputs match the live model:** credit = Baa-Treasury spread (`BAA10Y`, monthly `BAA - GS10` before 1986); "
        "curve = `T10Y3M` (monthly `GS10 - TB3MS` before 1982); "
        + ("equities = S&P 500 index (`^GSPC`) in place of SPY. " if equities_used else
           "**equities unavailable** - the `equities_rallying` adjustment was not evaluated. ")
        + "Breakevens (`T5YIE`) only exist from 2003, so earlier inflation pressure uses CPI/PCE alone.",
        "",
        "**Caveat:** revised FRED data with publication lags, not ALFRED vintages, so there is some look-ahead "
        "bias from data revisions. The current config was chosen on this same window, so these full-window "
        "numbers are in-sample - see the walk-forward section for an out-of-sample check.",
        "",
        f"**Result: {'PASS' if result.passed else 'FAIL'}.** {result.caught}/{len(result.recessions)} NBER recessions "
        f"caught (need at least {math.ceil(MIN_CATCH_SHARE * len(result.recessions))}). "
        f"{len(result.false_calls)} sustained false recession calls (max {MAX_FALSE_CALLS}).",
        "",
        "## Model vs simple baselines",
        "",
        "Same scoring for every row. *False-call months* counts every recession call more than "
        f"{FALSE_CALL_BUFFER_MONTHS} months from an NBER recession, including short ones; *sustained* false calls "
        f"are runs of {FALSE_CALL_MIN_MONTHS}+ such months. *Brier skill* scores the model's P(recession) + "
        "P(late_recession) against NBER months, relative to always forecasting the base rate (> 0 = better than "
        "the base rate). These are coincident scores: the probit is a 12-month-ahead model, so it is "
        "expected to call early.",
        "",
        *SUMMARY_HEADER,
        _summary_row(summarize(result, "**Composite model**")),
    ]
    for key, b in result.baselines.items():
        lines.append(_summary_row(summarize(b, BASELINES[key])))

    lines += [
        "",
        "## NBER recessions (composite model)",
        "",
        "| Recession | Caught | First `recession` call vs start (months) | `late_expansion` in prior 12m | `early_expansion` within 12m after |",
        "|---|---|---|---|---|",
    ]
    for r in result.recessions:
        lead = "n/a" if r.lead_months is None else f"{r.lead_months:+d}"
        lines.append(
            f"| {r.start:%Y-%m} to {r.end:%Y-%m} | {'yes' if r.caught else 'no'} | {lead} | "
            f"{'yes' if r.late_expansion_before else 'no'} | {'yes' if r.early_expansion_after else 'no'} |"
        )
    lines += ["", "## Sustained false recession calls", ""]
    lines += [f"- {a:%Y-%m} to {b:%Y-%m}" for a, b in result.false_calls] or ["- none"]

    if wf is not None:
        params = ", ".join(f"`{k}={v}`" for k, v in wf.best["overrides"].items())
        a, b = wf.calibration
        lines += [
            "",
            "## Walk-forward (out-of-sample)",
            "",
            f"Tuned on {TRAIN_WINDOW[0]:%Y-%m} to {TRAIN_WINDOW[1]:%Y-%m} only: {wf.grid_size} configs over "
            + ", ".join(f"`{k}`" for k in WALK_FORWARD_GRID)
            + ". Chosen by catch rate, then fewest sustained false calls, false-call months and phase changes. "
            f"Best on train: {params}.",
            "",
            *SUMMARY_HEADER,
            _summary_row({**wf.best, "label": "Train - best grid config"}),
            _summary_row({**wf.train_default, "label": "Train - current config"}),
            _summary_row({**wf.test_tuned, "label": f"**Test ({TEST_START:%Y}+) - tuned on train (out-of-sample)**"}),
            _summary_row({**wf.test_default, "label": f"Test ({TEST_START:%Y}+) - current config (in-sample)"}),
            "",
            f"The test window has only {wf.test_tuned['recessions']} NBER recession(s), so treat it as a sanity "
            "check, not a precise estimate.",
            "",
            f"**Calibration** (fitted on the train window only): `calibration=({a}, {b})`, i.e. "
            "P(in recession) = sigmoid(a + b x logit(raw P)). Brier skill vs the base rate: "
            f"train {_fmt(wf.train_brier_skill_raw, '+.2f')} raw -> {_fmt(wf.train_brier_skill_calibrated, '+.2f')} "
            f"calibrated (in-sample); **test {_fmt(wf.test_brier_skill_raw, '+.2f')} raw -> "
            f"{_fmt(wf.test_tuned['brier_skill'], '+.2f')} calibrated (out-of-sample)**.",
        ]

    if ablations:
        base = ablations[0]
        lines += [
            "",
            "## Ablation (full window, one component off at a time)",
            "",
            "Deltas vs the current config. A component that can be dropped with no loss in catches and no rise "
            "in false calls or phase changes is a candidate for removal.",
            "",
            "| Variant | Caught | Δ sustained false | Δ false-call months | Δ phase changes | Brier skill |",
            "|---|---|---|---|---|---|",
        ]
        for s in ablations:
            lines.append(
                f"| {s['label']} | {s['caught']}/{s['recessions']} | "
                f"{s['sustained_false_calls'] - base['sustained_false_calls']:+d} | "
                f"{s['false_call_months'] - base['false_call_months']:+d} | {s['flips'] - base['flips']:+d} | "
                f"{_fmt(s['brier_skill'], '+.2f')} |"
            )

    lines += ["", "## Phase vs NBER (months)", "", "| Phase | Expansion (USREC=0) | Recession (USREC=1) |", "|---|---|---|"]
    for phase, counts in result.confusion.items():
        lines.append(f"| {phase} | {counts[0]} | {counts[1]} |")
    lines += ["", "## Calls by year", "", "Each character is one month: E = early_expansion, L = late_expansion, "
              "R = recession, T = late_recession (trough), . = no call. Uppercase marks an NBER recession month.", "", "```"]
    codes = {"early_expansion": "e", "late_expansion": "l", "recession": "r", "late_recession": "t", None: "."}
    by_year: dict[int, str] = {}
    for m, phase, rec in result.calls:
        c = codes[phase]
        by_year[m.year] = by_year.get(m.year, "") + (c.upper() if rec else c)
    lines += [f"{year} {row}" for year, row in by_year.items()]
    lines += ["```", ""]
    expansion_2010s = [phase for m, phase, _ in result.calls if date(2010, 1, 1) <= m <= date(2017, 12, 1)]
    if expansion_2010s:
        mix = {p: expansion_2010s.count(p) for p in sorted(set(filter(None, expansion_2010s)))}
        lines += [f"2010-2017 phase mix (months): {mix}", ""]
    return "\n".join(lines)


async def _main(start: date, out: Path, walk: bool = False, ablate: bool = False,
                workers: int = 1) -> BacktestResult:
    from app.agents.market_researcher.config import load_settings

    settings = load_settings()
    fred = FredClient(settings.fred_api_key or "", timeout=30)
    try:
        today = date.today()
        history = await fetch_history(fred, today)
    finally:
        await fred.aclose()
    prices = fetch_equity_history(date(FETCH_START.year, 1, 1), today)
    end = f.shift_months(date(today.year, today.month, 1), -2)

    result = run_backtest(history, start, end, prices=prices, with_baselines=True)
    wf = walk_forward(history, prices, end, workers) if walk else None
    ablations = ablation(history, prices, start, end, workers) if ablate else None
    out.write_text(render_report(result, equities_used=bool(prices), wf=wf, ablations=ablations), encoding="utf-8")
    return result


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(1980, 1, 1))
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--walk-forward", action="store_true", help="tune on 1980-2005, score 2006+")
    parser.add_argument("--ablation", action="store_true", help="drop one component/adjustment at a time")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    result = asyncio.run(_main(args.start, args.out, args.walk_forward, args.ablation, args.workers))
    print(f"{'PASS' if result.passed else 'FAIL'}: {result.caught}/{len(result.recessions)} recessions caught, "
          f"{len(result.false_calls)} sustained false calls, {result.false_call_months} false-call months, "
          f"{result.flips} phase changes, Brier skill {_fmt(result.brier_skill, '+.2f')} -> {args.out}")


if __name__ == "__main__":
    main()
