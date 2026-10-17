"""
Deterministic transforms over SeriesPoint lists (guide §4.1): changes over
calendar windows, YoY, 3m annualized, z-scores and percentiles vs a
trailing window, "highest/lowest since" lookbacks, and trend gaps.

Pure stdlib, no I/O. Every function takes points sorted ascending by date
and returns None rather than guessing when there isn't enough data.
"""
import bisect
import calendar
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import (
    CHANGE_WINDOWS,
    PERIOD_DAYS,
    STALENESS_GRACE_DAYS,
    SeriesSpec,
)

# Max distance (days) between a requested past date and the observation
# used for it, per frequency - beyond this a change is reported as missing.
_YOY_TOLERANCE_DAYS = {"D": 5, "W": 4, "M": 3, "Q": 5}


# --- date helpers -----------------------------------------------------------

def shift_months(d: date, months: int) -> date:
    month_index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def shift_years(d: date, years: int) -> date:
    return shift_months(d, 12 * years)


# --- lookups ----------------------------------------------------------------

def truncate(points: list[SeriesPoint], end: date) -> list[SeriesPoint]:
    """Points with date <= end."""
    idx = bisect.bisect_right([p.date for p in points], end)
    return points[:idx]


def window(points: list[SeriesPoint], start: date, end: date) -> list[SeriesPoint]:
    dates = [p.date for p in points]
    return points[bisect.bisect_left(dates, start):bisect.bisect_right(dates, end)]


def value_at_or_before(points: list[SeriesPoint], d: date) -> Optional[SeriesPoint]:
    idx = bisect.bisect_right([p.date for p in points], d)
    return points[idx - 1] if idx else None


def point_near(
    points: list[SeriesPoint], target: date, tolerance_days: int, before: Optional[date] = None
) -> Optional[SeriesPoint]:
    """The observation closest to `target` (ties go to the earlier one),
    strictly before `before` if given, within `tolerance_days`."""
    return _nearest(points, [p.date for p in points], target, tolerance_days, before)


def _nearest(
    points: list[SeriesPoint], dates: list[date], target: date, tolerance_days: int, before: Optional[date]
) -> Optional[SeriesPoint]:
    limit = bisect.bisect_left(dates, before) if before is not None else len(dates)
    if limit == 0:
        return None
    idx = bisect.bisect_right(dates, target, 0, limit)
    options = []
    if idx > 0:
        options.append(points[idx - 1])
    if idx < limit:
        options.append(points[idx])
    best = min(options, key=lambda p: (abs((p.date - target).days), p.date > target))
    if abs((best.date - target).days) > tolerance_days:
        return None
    return best


def _change_tolerance(days: int) -> int:
    return max(5, int(days * 0.25))


def change_over(points: list[SeriesPoint], days: int) -> Optional[float]:
    """Latest value minus the value ~`days` calendar days earlier."""
    if len(points) < 2:
        return None
    last = points[-1]
    past = point_near(points, last.date - timedelta(days=days), _change_tolerance(days), before=last.date)
    return None if past is None else last.value - past.value


def pct_change_over(points: list[SeriesPoint], days: int) -> Optional[float]:
    """Percent change of the latest value vs ~`days` calendar days earlier."""
    if len(points) < 2:
        return None
    last = points[-1]
    past = point_near(points, last.date - timedelta(days=days), _change_tolerance(days), before=last.date)
    if past is None or past.value == 0:
        return None
    return (last.value / past.value - 1) * 100


# --- transforms -------------------------------------------------------------

def yoy_series(points: list[SeriesPoint], frequency: str) -> list[SeriesPoint]:
    """Year-over-year % change at each observation that has a year-ago match."""
    tolerance = _YOY_TOLERANCE_DAYS.get(frequency, 5)
    dates = [p.date for p in points]
    out: list[SeriesPoint] = []
    for p in points:
        past = _nearest(points, dates, shift_years(p.date, -1), tolerance, p.date)
        if past is not None and past.value != 0:
            out.append(SeriesPoint(p.date, (p.value / past.value - 1) * 100))
    return out


def diff_avg_series(points: list[SeriesPoint], periods: int = 3) -> list[SeriesPoint]:
    """Average per-period difference over the last `periods` observations
    (e.g. payrolls: 3-month average monthly change)."""
    return [
        SeriesPoint(points[i].date, (points[i].value - points[i - periods].value) / periods)
        for i in range(periods, len(points))
    ]


def annualized_series(points: list[SeriesPoint], periods: int = 3, periods_per_year: int = 12) -> list[SeriesPoint]:
    """Annualized % change over the last `periods` observations
    (monthly index: 3m annualized = (v_t / v_{t-3})^4 - 1)."""
    exponent = periods_per_year / periods
    out = []
    for i in range(periods, len(points)):
        prev = points[i - periods].value
        if prev > 0 and points[i].value > 0:
            out.append(SeriesPoint(points[i].date, ((points[i].value / prev) ** exponent - 1) * 100))
    return out


def moving_average_series(points: list[SeriesPoint], n: int) -> list[SeriesPoint]:
    """Trailing n-observation moving average (e.g. 4-week average claims)."""
    out = []
    running = 0.0
    for i, p in enumerate(points):
        running += p.value
        if i >= n:
            running -= points[i - n].value
        if i >= n - 1:
            out.append(SeriesPoint(p.date, running / n))
    return out


def transform(spec: SeriesSpec, points: list[SeriesPoint]) -> list[SeriesPoint]:
    if spec.transform == "yoy":
        return yoy_series(points, spec.frequency)
    if spec.transform == "diff_3m_avg":
        return diff_avg_series(points, 3)
    return points


# --- statistics -------------------------------------------------------------

def trailing_values(points: list[SeriesPoint], years: Optional[int]) -> list[float]:
    if not points:
        return []
    if years is None:
        return [p.value for p in points]
    start = shift_years(points[-1].date, -years)
    return [p.value for p in window(points, start, points[-1].date)]


def zscore(points: list[SeriesPoint], years: Optional[int] = 10, min_points: int = 8) -> Optional[float]:
    values = trailing_values(points, years)
    if len(values) < min_points:
        return None
    stdev = statistics.pstdev(values)
    if stdev == 0:
        return 0.0
    return (values[-1] - statistics.fmean(values)) / stdev


def percentile(points: list[SeriesPoint], years: Optional[int] = 10, min_points: int = 8) -> Optional[float]:
    """Mid-rank percentile (0-100) of the latest value within the trailing
    window - ties count half, so a flat series sits at the 50th."""
    values = trailing_values(points, years)
    if len(values) < min_points:
        return None
    latest = values[-1]
    below = sum(1 for v in values if v < latest)
    equal = sum(1 for v in values if v == latest)
    return 100.0 * (below + 0.5 * equal) / len(values)


@dataclass(frozen=True)
class Extreme:
    """How unusual the latest value is vs its own history.

    `since` is the last date the series was at least as high (or low) as
    now; None means the latest value is the extreme of all fetched history,
    in which case `history_start` says how far back that history goes.
    """
    since: Optional[date]
    years: Optional[float]
    history_start: date


def highest_since(points: list[SeriesPoint]) -> Optional[Extreme]:
    return _extreme_since(points, higher=True)


def lowest_since(points: list[SeriesPoint]) -> Optional[Extreme]:
    return _extreme_since(points, higher=False)


def _extreme_since(points: list[SeriesPoint], higher: bool) -> Optional[Extreme]:
    if len(points) < 2:
        return None
    latest = points[-1]
    for p in reversed(points[:-1]):
        if (p.value >= latest.value) if higher else (p.value <= latest.value):
            return Extreme(p.date, (latest.date - p.date).days / 365.25, points[0].date)
    return Extreme(None, None, points[0].date)


def trend_gap(points: list[SeriesPoint], days: int = 365) -> Optional[float]:
    """Latest value minus its trailing `days` moving average."""
    if not points:
        return None
    latest = points[-1]
    values = [p.value for p in window(points, latest.date - timedelta(days=days), latest.date)]
    if len(values) < 3:
        return None
    return latest.value - statistics.fmean(values)


def is_stale(frequency: str, latest_date: date, as_of: date) -> bool:
    max_age = PERIOD_DAYS[frequency] + STALENESS_GRACE_DAYS[frequency]
    return (as_of - latest_date).days > max_age


# --- per-indicator bundle ---------------------------------------------------

@dataclass
class IndicatorFeatures:
    spec: SeriesSpec
    raw: list[SeriesPoint]
    derived: list[SeriesPoint]
    value: float
    observation_date: date
    changes: dict[str, float] = field(default_factory=dict)
    zscore_10y: Optional[float] = None
    percentile_10y: Optional[float] = None
    percentile_full: Optional[float] = None
    trend_gap_12m: Optional[float] = None
    annualized_3m: Optional[float] = None
    stale: bool = False
    stats_window_years: Optional[float] = None  # history actually behind zscore_10y/percentile_10y


def compute_indicator_features(spec: SeriesSpec, points: list[SeriesPoint], as_of: date) -> Optional[IndicatorFeatures]:
    raw = truncate(points, as_of)
    derived = transform(spec, raw)
    if not derived:
        return None
    latest = derived[-1]
    changes = {}
    for label, days in CHANGE_WINDOWS[spec.frequency].items():
        delta = change_over(derived, days)
        if delta is not None:
            changes[label] = round(delta, 4)

    annualized = None
    if spec.transform == "yoy" and spec.frequency == "M":
        ann = annualized_series(raw, 3, 12)
        annualized = ann[-1].value if ann else None

    return IndicatorFeatures(
        spec=spec,
        raw=raw,
        derived=derived,
        value=latest.value,
        observation_date=latest.date,
        changes=changes,
        zscore_10y=zscore(derived, 10),
        percentile_10y=percentile(derived, 10),
        percentile_full=percentile(derived, None),
        trend_gap_12m=trend_gap(derived, 365),
        annualized_3m=annualized,
        stale=is_stale(spec.frequency, latest.date, as_of),
        stats_window_years=stats_window_years(derived, 10),
    )


def stats_window_years(points: list[SeriesPoint], years: int = 10) -> Optional[float]:
    """Years of history the trailing-`years` statistics actually cover - less
    than `years` when the source has a short history (e.g. ICE BofA OAS on FRED)."""
    if len(points) < 2:
        return None
    return round(min(float(years), (points[-1].date - points[0].date).days / 365.25), 1)


def signal_for(features: IndicatorFeatures) -> str:
    spec = features.spec
    delta = features.changes.get(spec.signal_change)
    if delta is None or spec.signal_threshold <= 0:
        return "neutral"
    if delta > spec.signal_threshold:
        return spec.up_signal
    if delta < -spec.signal_threshold:
        return spec.down_signal
    return "neutral"
