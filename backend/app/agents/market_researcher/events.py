"""
Rule-based notable-event detection (guide §4.2).

Each rule reads raw series (FRED ids) and/or price histories (symbols),
returns zero or more `Event`s, and cites the ids it used as evidence.
Every threshold lives in config.EventThresholds. Descriptions carry the
actual numbers and lookbacks - e.g. "highest since 2007-06-12 (19.3
years)", never "all-time high" unless it really is the extreme of the
fetched history, in which case the history start is stated.
"""
from datetime import date, timedelta
from typing import Callable, Optional

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import EVENT_THRESHOLDS, EventThresholds
from app.agents.market_researcher.schemas import Event

Series = dict[str, list[SeriesPoint]]

_YIELD_NAMES = {"DGS10": "10-year Treasury yield", "DGS30": "30-year Treasury yield"}
_CURVE_NAMES = {"T10Y3M": "10Y-3M curve", "T10Y2Y": "10Y-2Y curve"}


def _ordinal(n: float) -> str:
    k = int(round(n))
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def _get(series: Series, key: str, as_of: date) -> list[SeriesPoint]:
    return f.truncate(series.get(key) or [], as_of)


def yield_highs(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    events = []
    for sid, name in _YIELD_NAMES.items():
        pts = _get(series, sid, as_of)
        ext = f.highest_since(pts)
        if ext is None:
            continue
        latest = pts[-1]
        if ext.since is None:
            years = (latest.date - ext.history_start).days / 365.25
            if years < t.yield_high_min_years:
                continue
            events.append(Event(
                id=f"{sid.lower()}_high_in_history",
                severity="major",
                description=(
                    f"{name} at {latest.value:.2f}% on {latest.date} is the highest in the fetched "
                    f"history (since {ext.history_start})."
                ),
                evidence=[sid],
            ))
        elif ext.years >= t.yield_high_min_years:
            events.append(Event(
                id=f"{sid.lower()}_multi_year_high",
                severity="major" if ext.years >= t.yield_high_major_years else "notable",
                description=(
                    f"{name} at {latest.value:.2f}% on {latest.date} is the highest since "
                    f"{ext.since} ({ext.years:.1f} years)."
                ),
                evidence=[sid],
            ))
    return events


def sharp_yield_move(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = _get(series, "DGS10", as_of)
    w, m = f.change_over(pts, 7), f.change_over(pts, 30)
    parts = []
    if w is not None and abs(w) > t.yield_move_1w:
        parts.append(f"{w * 100:+.0f}bp over 1 week")
    if m is not None and abs(m) > t.yield_move_1m:
        parts.append(f"{m * 100:+.0f}bp over 1 month")
    if not parts:
        return []
    direction = "up" if (w or m or 0) > 0 else "down"
    return [Event(
        id=f"dgs10_sharp_move_{direction}",
        severity="notable",
        description=f"10-year Treasury yield moved sharply {direction}: " + ", ".join(parts) + f" (now {pts[-1].value:.2f}%).",
        evidence=["DGS10"],
    )]


def curve_crossings(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    events = []
    for sid, name in _CURVE_NAMES.items():
        pts = _get(series, sid, as_of)
        if len(pts) < 2:
            continue
        latest = pts[-1]
        recent = f.window(pts, latest.date - timedelta(days=t.curve_cross_window_days), latest.date)
        crossed = any((a.value < 0) != (b.value < 0) for a, b in zip(recent, recent[1:]))
        if crossed and latest.value >= 0:
            inverted_days = _days_inverted_in(pts, latest.date - timedelta(days=730), latest.date)
            long_inversion = inverted_days >= t.long_inversion_days
            events.append(Event(
                id=f"{sid.lower()}_uninverted",
                severity="major" if long_inversion else "notable",
                description=(
                    f"{name} turned positive ({latest.value:.2f}pp on {latest.date})"
                    + (f" after about {inverted_days} days inverted in the prior 2 years; re-steepening after a long "
                       "inversion has historically preceded recessions." if long_inversion else ".")
                ),
                evidence=[sid],
            ))
        elif crossed:
            events.append(Event(
                id=f"{sid.lower()}_inverted",
                severity="notable",
                description=f"{name} inverted ({latest.value:.2f}pp on {latest.date}).",
                evidence=[sid],
            ))
        elif latest.value < 0:
            events.append(Event(
                id=f"{sid.lower()}_still_inverted",
                severity="info",
                description=f"{name} remains inverted at {latest.value:.2f}pp.",
                evidence=[sid],
            ))
    return events


def _days_inverted_in(pts: list[SeriesPoint], start: date, end: date) -> int:
    """Approximate calendar days the spread spent below zero in [start, end]."""
    span = f.window(pts, start, end)
    days = 0
    for a, b in zip(span, span[1:]):
        if a.value < 0:
            days += (b.date - a.date).days
    return days


def sahm_rule(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = _get(series, "SAHMREALTIME", as_of)
    if not pts:
        return []
    v = pts[-1]
    if v.value >= t.sahm_trigger:
        return [Event(id="sahm_rule_triggered", severity="major",
                      description=f"Sahm rule triggered: real-time indicator at {v.value:.2f}pp ({v.date}), at or above {t.sahm_trigger:.2f}.",
                      evidence=["SAHMREALTIME", "UNRATE"])]
    if v.value >= t.sahm_warning:
        return [Event(id="sahm_rule_warning", severity="notable",
                      description=f"Sahm rule indicator rising: {v.value:.2f}pp ({v.date}); trigger is {t.sahm_trigger:.2f}.",
                      evidence=["SAHMREALTIME", "UNRATE"])]
    return []


def claims_rising(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    ma = f.moving_average_series(_get(series, "ICSA", as_of), 4)
    if len(ma) < 10:
        return []
    latest = ma[-1]
    year = f.window(ma, latest.date - timedelta(days=365), latest.date)
    low = min(p.value for p in year)
    if low <= 0:
        return []
    rise = latest.value / low - 1
    if rise <= t.claims_rise_from_low:
        return []
    return [Event(
        id="jobless_claims_rising", severity="notable",
        description=(f"Initial jobless claims 4-week average at {latest.value:,.0f} is {rise * 100:.0f}% above its "
                     f"52-week low of {low:,.0f}."),
        evidence=["ICSA"],
    )]


def credit_stress(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    """Widening: ICE BofA HY OAS when available (only ~3 years on FRED, fine
    for a 3-month change), else the Baa-Treasury spread. Level: Baa-Treasury
    spread vs its own last 10 years - long enough history for a percentile."""
    hy = _get(series, "BAMLH0A0HYM2", as_of)
    baa = _get(series, "BAA10Y", as_of)
    parts, evidence = [], []
    hy_widening, baa_widening = f.change_over(hy, 91), f.change_over(baa, 91)
    if hy_widening is not None and hy_widening > t.hy_oas_3m_widening:
        parts.append(f"high-yield OAS widened {hy_widening * 100:.0f}bp in 3 months to {hy[-1].value:.2f}%")
        evidence.append("BAMLH0A0HYM2")
    elif baa_widening is not None and baa_widening > t.credit_spread_3m_widening:
        parts.append(f"the Baa-Treasury spread widened {baa_widening * 100:.0f}bp in 3 months to {baa[-1].value:.2f}pp")
        evidence.append("BAA10Y")
    pct = f.percentile(baa, 10)
    if pct is not None and pct > t.credit_high_percentile:
        years = min(10.0, (baa[-1].date - baa[0].date).days / 365.25)
        parts.append(f"the Baa-Treasury spread at {baa[-1].value:.2f}pp is at the {_ordinal(pct)} percentile of the last {years:.1f} years")
        evidence.append("BAA10Y")
    if not parts:
        return []
    return [Event(
        id="credit_stress", severity="major" if len(parts) == 2 else "notable",
        description="Credit stress: " + "; ".join(parts) + ".",
        evidence=sorted(set(evidence)),
    )]


def financial_conditions(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = _get(series, "NFCI", as_of)
    if not pts:
        return []
    latest = pts[-1]
    rise = f.change_over(pts, 91)
    if latest.value > t.nfci_tight_level:
        return [Event(id="financial_conditions_tight", severity="notable",
                      description=f"Chicago Fed NFCI at {latest.value:.2f} (above 0 = tighter than average).",
                      evidence=["NFCI"])]
    if rise is not None and rise > t.nfci_3m_rise:
        return [Event(id="financial_conditions_tightening", severity="notable",
                      description=f"Financial conditions tightening: NFCI up {rise:.2f} over 3 months to {latest.value:.2f}.",
                      evidence=["NFCI"])]
    return []


def inflation_reacceleration(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    raw = _get(series, "CPILFESL", as_of)
    yoy = f.yoy_series(raw, "M")
    ann = f.annualized_series(raw, 3, 12)
    if not yoy or not ann or yoy[-1].date != ann[-1].date:
        return []
    gap = ann[-1].value - yoy[-1].value
    if gap <= t.inflation_reaccel_gap:
        return []
    return [Event(
        id="core_inflation_reaccelerating", severity="notable",
        description=(f"Core CPI re-accelerating: 3-month annualized {ann[-1].value:.2f}% vs {yoy[-1].value:.2f}% YoY "
                     f"({ann[-1].date})."),
        evidence=["CPILFESL"],
    )]


def equity_drawdown(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = f.truncate(prices.get("SPY") or [], as_of)
    if len(pts) < 20:
        return []
    latest = pts[-1]
    high = max(p.value for p in f.window(pts, latest.date - timedelta(days=365), latest.date))
    drawdown = 1 - latest.value / high
    if drawdown > t.equity_bear:
        severity, label = "major", "bear market"
    elif drawdown > t.equity_correction:
        severity, label = "notable", "correction"
    else:
        return []
    return [Event(id=f"spy_{label.replace(' ', '_')}", severity=severity,
                  description=f"S&P 500 (SPY) is {drawdown * 100:.1f}% below its 52-week high ({label}).",
                  evidence=["SPY"])]


def volatility_spike(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = f.truncate(prices.get("^VIX") or [], as_of)
    evidence = "^VIX"
    if not pts:
        pts, evidence = _get(series, "VIXCLS", as_of), "VIXCLS"
    if not pts:
        return []
    latest = pts[-1]
    weekly = f.pct_change_over(pts, 7)
    if latest.value > t.vix_spike_level or (weekly is not None and weekly > t.vix_spike_1w_rise * 100):
        detail = f"VIX at {latest.value:.2f}" + (f", up {weekly:.0f}% in a week" if weekly is not None and weekly > 0 else "")
        return [Event(id="volatility_spike", severity="notable", description=detail + ".", evidence=[evidence])]
    return []


def oil_shock(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = f.truncate(prices.get("CL=F") or [], as_of)
    change = f.pct_change_over(pts, 91)
    if change is None or change <= t.oil_shock_3m_rise * 100:
        return []
    return [Event(id="oil_shock", severity="notable",
                  description=f"WTI crude up {change:.0f}% over 3 months to ${pts[-1].value:.2f}/bbl.",
                  evidence=["CL=F"])]


def policy_rate_change(series: Series, prices: Series, as_of: date, t: EventThresholds) -> list[Event]:
    pts = _get(series, "DFEDTARU", as_of)
    if len(pts) < 2:
        return []
    latest = pts[-1]
    past = f.value_at_or_before(pts, latest.date - timedelta(days=t.policy_change_window_days))
    if past is None or abs(latest.value - past.value) < 0.01:
        return []
    delta_bp = (latest.value - past.value) * 100
    verb = "raised" if delta_bp > 0 else "cut"
    lower = f.value_at_or_before(_get(series, "DFEDTARL", as_of), latest.date)
    target = f"{lower.value:.2f}-{latest.value:.2f}%" if lower else f"upper bound {latest.value:.2f}%"
    return [Event(id=f"fed_{verb}", severity="notable",
                  description=f"Fed {verb} its target range by {abs(delta_bp):.0f}bp in the last {t.policy_change_window_days} days (now {target}).",
                  evidence=["DFEDTARU", "DFEDTARL"])]


RULES: tuple[Callable[[Series, Series, date, EventThresholds], list[Event]], ...] = (
    yield_highs,
    sharp_yield_move,
    curve_crossings,
    sahm_rule,
    claims_rising,
    credit_stress,
    financial_conditions,
    inflation_reacceleration,
    equity_drawdown,
    volatility_spike,
    oil_shock,
    policy_rate_change,
)

_SEVERITY_ORDER = {"major": 0, "notable": 1, "info": 2}


def detect_events(
    series: Series,
    prices: Optional[Series],
    as_of: date,
    thresholds: EventThresholds = EVENT_THRESHOLDS,
) -> list[Event]:
    events: list[Event] = []
    for rule in RULES:
        events.extend(rule(series, prices or {}, as_of, thresholds))
    return sorted(events, key=lambda e: _SEVERITY_ORDER[e.severity])
