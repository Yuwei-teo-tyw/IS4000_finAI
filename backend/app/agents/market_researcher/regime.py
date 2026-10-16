"""
Economic cycle phase classifier and recession probability (guide §4.3-4.4).

Transparent and score-based so every call can be explained and backtested:

1. Composites from z-scored indicators - growth level G, growth momentum M,
   inflation pressure I, policy/financial stance P.
2. Base quadrant scores: score[phase] = base_scale * (sG*G + w_m*sM*M), with
   (sG, sM) = (+,+) early_expansion, (+,-) late_expansion, (-,-) recession,
   (-,+) late_recession - so the argmax is exactly the growth/momentum
   quadrant.
3. Confirmation adjustments shift scores (never hard overrides).
4. Softmax with a temperature -> probabilities; confidence from the margin
   between the top two.
5. Hysteresis vs the previous classification.

Operates on raw series dicts (FRED ids -> SeriesPoint lists) so the live
service and the backtest share exactly the same code path. All weights and
thresholds live in config.RegimeConfig.
"""
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import NormalDist, fmean, pstdev
from typing import Optional

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import (
    PHASES,
    PROBIT_ALPHA,
    PROBIT_AVERAGE_DAYS,
    PROBIT_BETA,
    REGIME_CONFIG,
    RegimeConfig,
)
from app.agents.market_researcher.schemas import Driver, Regime

Series = dict[str, list[SeriesPoint]]

# (sign on G, sign on M) per phase.
PHASE_SIGNS: dict[str, tuple[int, int]] = {
    "early_expansion": (1, 1),
    "late_expansion": (1, -1),
    "recession": (-1, -1),
    "late_recession": (-1, 1),
}

# Growth components where a higher value means *weaker* growth.
_INVERTED = {"UNRATE_GAP", "ICSA_TREND"}

COMPONENT_LABELS = {
    "INDPRO_YOY": "Industrial production YoY (INDPRO)",
    "REAL_RETAIL_YOY": "Real retail sales YoY (RSAFS less CPIAUCSL)",
    "PAYEMS_3M_AVG": "Payrolls 3m avg change (PAYEMS)",
    "GDPC1_YOY": "Real GDP YoY (GDPC1)",
    "UNRATE_GAP": "Unemployment vs 12m low (UNRATE)",
    "ICSA_TREND": "Jobless claims 4wk avg YoY (ICSA)",
}


# --- recession probability --------------------------------------------------

def recession_probability(series: Series, as_of: date) -> Optional[float]:
    """NY Fed yield-curve probit on the trailing-month average 10Y-3M spread.
    A model estimate, not a forecast of record."""
    pts = f.truncate(series.get("T10Y3M") or [], as_of)
    if not pts:
        return None
    recent = f.window(pts, pts[-1].date - timedelta(days=PROBIT_AVERAGE_DAYS), pts[-1].date)
    spread = fmean(p.value for p in recent)
    return NormalDist().cdf(PROBIT_ALPHA + PROBIT_BETA * spread)


# --- component series -------------------------------------------------------

def _align_diff(a: list[SeriesPoint], b: list[SeriesPoint]) -> list[SeriesPoint]:
    b_by_date = {p.date: p.value for p in b}
    return [SeriesPoint(p.date, p.value - b_by_date[p.date]) for p in a if p.date in b_by_date]


def _gap_to_trailing_min(points: list[SeriesPoint], days: int = 365) -> list[SeriesPoint]:
    """Value minus its trailing-`days` minimum. Scans back at most 14
    observations - enough for 12 months of a monthly series (UNRATE)."""
    out = []
    for i, p in enumerate(points):
        start = p.date - timedelta(days=days)
        lows = [q.value for q in points[max(0, i - 14):i + 1] if q.date >= start]
        out.append(SeriesPoint(p.date, p.value - min(lows)))
    return out


def growth_components(series: Series) -> dict[str, list[SeriesPoint]]:
    """Derived monthly/weekly series feeding the growth composite."""
    comps: dict[str, list[SeriesPoint]] = {}
    if series.get("INDPRO"):
        comps["INDPRO_YOY"] = f.yoy_series(series["INDPRO"], "M")
    if series.get("RSAFS") and series.get("CPIAUCSL"):
        comps["REAL_RETAIL_YOY"] = _align_diff(
            f.yoy_series(series["RSAFS"], "M"), f.yoy_series(series["CPIAUCSL"], "M")
        )
    if series.get("PAYEMS"):
        comps["PAYEMS_3M_AVG"] = f.diff_avg_series(series["PAYEMS"], 3)
    if series.get("GDPC1"):
        comps["GDPC1_YOY"] = f.yoy_series(series["GDPC1"], "Q")
    if series.get("UNRATE"):
        comps["UNRATE_GAP"] = _gap_to_trailing_min(series["UNRATE"], 365)
    if series.get("ICSA"):
        comps["ICSA_TREND"] = f.yoy_series(f.moving_average_series(series["ICSA"], 4), "W")
    return {k: v for k, v in comps.items() if v}


def _momentum(points: list[SeriesPoint], months: int, years: int) -> Optional[float]:
    """Change over `months`, in units of the component's trailing std dev."""
    if len(points) < 8:
        return None
    latest = points[-1]
    past = f.point_near(points, f.shift_months(latest.date, -months), 20, before=latest.date)
    values = f.trailing_values(points, years)
    sd = pstdev(values) if len(values) > 1 else 0.0
    if past is None or sd == 0:
        return None
    return (latest.value - past.value) / sd


def _latest(series: Series, key: str) -> Optional[SeriesPoint]:
    pts = series.get(key)
    return pts[-1] if pts else None


def _weighted_mean(items: list[tuple[float, float]]) -> Optional[float]:
    total = sum(w for w, _ in items)
    return sum(w * v for w, v in items) / total if total else None


# --- classifier -------------------------------------------------------------

@dataclass
class _Adjustment:
    phase: str
    weight: float
    label: str
    indicator: str
    value: Optional[float] = None


@dataclass
class RegimeInputs:
    """Everything the classifier computed, kept for drivers/conflicts and tests."""
    G: Optional[float] = None
    M: Optional[float] = None
    I: Optional[float] = None  # noqa: E741 - the guide's name for inflation pressure
    P: Optional[float] = None
    growth_z: dict[str, float] = field(default_factory=dict)
    growth_momentum: dict[str, float] = field(default_factory=dict)
    growth_latest: dict[str, float] = field(default_factory=dict)
    growth_weights: dict[str, float] = field(default_factory=dict)
    adjustments: list[_Adjustment] = field(default_factory=list)
    recession_prob_12m: Optional[float] = None


def compute_inputs(series: Series, as_of: date, prices: Optional[Series] = None,
                   cfg: RegimeConfig = REGIME_CONFIG) -> RegimeInputs:
    s = {k: f.truncate(v, as_of) for k, v in series.items() if v}
    prices = {k: f.truncate(v, as_of) for k, v in (prices or {}).items() if v}
    out = RegimeInputs(recession_prob_12m=recession_probability(s, as_of))

    # Step 1a: growth level G and momentum M.
    g_items, m_items = [], []
    for name, pts in growth_components(s).items():
        weight = cfg.growth_weights.get(name, 0.0)
        sign = -1 if name in _INVERTED else 1
        z = f.zscore(pts, cfg.zscore_years)
        mom = _momentum(pts, cfg.momentum_months, cfg.zscore_years)
        if z is None or weight == 0:
            continue
        out.growth_z[name] = sign * z
        out.growth_latest[name] = pts[-1].value
        out.growth_weights[name] = weight
        g_items.append((weight, sign * z))
        if mom is not None:
            out.growth_momentum[name] = sign * mom
            m_items.append((weight, sign * mom))
    if len(g_items) >= 2:
        out.G = _weighted_mean(g_items)
    if len(m_items) >= 2:
        out.M = _weighted_mean(m_items)

    # Step 1b: inflation pressure I.
    core_cpi = s.get("CPILFESL") or []
    inflation_values = {
        "CPILFESL_YOY": _last_value(f.yoy_series(core_cpi, "M")),
        "PCEPILFE_YOY": _last_value(f.yoy_series(s.get("PCEPILFE") or [], "M")),
        "CPILFESL_3M_ANN": _last_value(f.annualized_series(core_cpi, 3, 12)),
        "T5YIE": _last_value(s.get("T5YIE") or []),
    }
    i_items = [
        (1.0, (inflation_values[k] - anchor) / scale)
        for k, (anchor, scale) in cfg.inflation_anchors.items()
        if inflation_values.get(k) is not None
    ]
    out.I = _weighted_mean(i_items)

    # Step 1c: policy / financial stance P (positive = restrictive).
    dff = _latest(s, "DFF")
    core_pce = inflation_values["PCEPILFE_YOY"] or inflation_values["CPILFESL_YOY"]
    curve = _latest(s, "T10Y3M")
    hy = s.get("BAMLH0A0HYM2") or []
    nfci = _latest(s, "NFCI")
    p_parts = {
        "REAL_POLICY_RATE": ((dff.value - core_pce - cfg.neutral_real_rate) / cfg.real_rate_scale)
        if dff and core_pce is not None else None,
        "CURVE_FLATNESS": (-curve.value / cfg.curve_scale) if curve else None,
        "HY_OAS": f.zscore(hy, cfg.zscore_years),
        "NFCI": nfci.value if nfci else None,
    }
    out.P = _weighted_mean([(cfg.policy_weights[k], v) for k, v in p_parts.items() if v is not None])

    # Step 3: confirmation adjustments.
    out.adjustments = _adjustments(s, prices, out, inflation_values, p_parts, cfg)
    return out


def _last_value(points: list[SeriesPoint]) -> Optional[float]:
    return points[-1].value if points else None


def _adjustments(s: Series, prices: Series, inp: RegimeInputs, inflation: dict,
                 p_parts: dict, cfg: RegimeConfig) -> list[_Adjustment]:
    adj: list[_Adjustment] = []
    w, strong = cfg.adjustment_weight, cfg.strong_adjustment_weight

    unrate = s.get("UNRATE") or []
    unrate_gap = inp.growth_latest.get("UNRATE_GAP")
    unrate_pct = f.percentile(unrate, cfg.zscore_years)
    unrate_3m = f.change_over(unrate, 92)
    curve = _latest(s, "T10Y3M")
    dff = s.get("DFF") or []
    dff_6m = f.change_over(dff, 182)
    hy = s.get("BAMLH0A0HYM2") or []
    hy_pct = f.percentile(hy, cfg.zscore_years)
    hy_1m, hy_3m = f.change_over(hy, 30), f.change_over(hy, 91)
    sahm = _latest(s, "SAHMREALTIME")
    payrolls = inp.growth_latest.get("PAYEMS_3M_AVG")
    claims_trend = inp.growth_latest.get("ICSA_TREND")
    real_rate = p_parts.get("REAL_POLICY_RATE")

    # Toward late_expansion
    if unrate_gap is not None and unrate_gap <= cfg.unrate_near_low_gap and unrate_pct is not None and unrate_pct < 40:
        adj.append(_Adjustment("late_expansion", w, "Unemployment near its cycle low", "UNRATE", unrate[-1].value))
    if inp.I is not None and inp.I > cfg.inflation_elevated:
        adj.append(_Adjustment("late_expansion", w, "Inflation pressure elevated", "I", inp.I))
    if inp.P is not None and inp.P > cfg.policy_restrictive:
        adj.append(_Adjustment("late_expansion", w, "Policy/financial stance restrictive", "P", inp.P))
    if curve and curve.value < cfg.curve_flat:
        adj.append(_Adjustment("late_expansion", w, "Yield curve flat or inverted", "T10Y3M", curve.value))
    if hy_pct is not None and hy_3m is not None and hy_pct < cfg.hy_tight_percentile and hy_3m > 0:
        adj.append(_Adjustment("late_expansion", w, "Credit spreads tight but widening", "BAMLH0A0HYM2", hy[-1].value))
    if dff_6m is not None and dff_6m > cfg.tightening_6m:
        adj.append(_Adjustment("late_expansion", w, "Fed tightening over 6 months", "DFF", dff_6m))

    # Toward early_expansion
    if unrate_pct is not None and unrate_3m is not None and unrate_pct > cfg.unrate_high_percentile and unrate_3m < 0:
        adj.append(_Adjustment("early_expansion", w, "Unemployment high but falling", "UNRATE", unrate[-1].value))
    if curve and curve.value > cfg.curve_steep:
        adj.append(_Adjustment("early_expansion", w, "Yield curve steep", "T10Y3M", curve.value))
    if (dff_6m is not None and dff_6m < cfg.easing_6m) or (real_rate is not None and real_rate < 0):
        adj.append(_Adjustment("early_expansion", w, "Policy easing or accommodative", "DFF", dff[-1].value if dff else None))
    if inp.I is not None and inp.I < 0:
        adj.append(_Adjustment("early_expansion", w, "Inflation subdued", "I", inp.I))
    if hy_pct is not None and hy_3m is not None and hy_pct > 50 and hy_3m < 0:
        adj.append(_Adjustment("early_expansion", w, "Credit spreads tightening from wide levels", "BAMLH0A0HYM2", hy[-1].value))

    # Toward recession
    if sahm and sahm.value >= 0.5:
        adj.append(_Adjustment("recession", strong, "Sahm rule triggered", "SAHMREALTIME", sahm.value))
    if claims_trend is not None and claims_trend > cfg.claims_surge * 100:
        adj.append(_Adjustment("recession", w, "Jobless claims surging vs a year ago", "ICSA", claims_trend))
    if hy_3m is not None and hy_3m > 1.0:
        adj.append(_Adjustment("recession", w, "High-yield spreads blowing out", "BAMLH0A0HYM2", hy_3m))
    if payrolls is not None and payrolls < 0:
        adj.append(_Adjustment("recession", strong, "Payrolls contracting (3m avg)", "PAYEMS", payrolls))
    if inp.recession_prob_12m is not None and inp.recession_prob_12m > cfg.probit_high:
        adj.append(_Adjustment("recession", w, "Yield-curve recession probability high", "T10Y3M", inp.recession_prob_12m))

    # Toward late_recession
    if dff_6m is not None and dff_6m < cfg.aggressive_easing_6m:
        adj.append(_Adjustment("late_recession", w, "Fed easing aggressively", "DFF", dff_6m))
    if hy_pct is not None and hy_1m is not None and hy_pct > cfg.hy_wide_percentile and hy_1m < 0:
        adj.append(_Adjustment("late_recession", w, "Wide credit spreads rolling over", "BAMLH0A0HYM2", hy[-1].value))
    claims_ma = f.moving_average_series(s.get("ICSA") or [], 4)
    if claims_trend is not None and claims_trend > 10 and len(claims_ma) > 8 and claims_ma[-1].value < claims_ma[-9].value:
        adj.append(_Adjustment("late_recession", w, "Jobless claims elevated but past their peak", "ICSA", claims_ma[-1].value))
    spy = prices.get("SPY") or []
    if spy:
        low = min(p.value for p in f.window(spy, spy[-1].date - timedelta(days=182), spy[-1].date))
        if low > 0 and spy[-1].value / low - 1 > cfg.equity_rally_off_low:
            adj.append(_Adjustment("late_recession", w, "Equities rallying off their lows", "SPY", spy[-1].value))
    permits_3m = f.pct_change_over(s.get("PERMIT") or [], 92)
    sentiment_3m = f.change_over(s.get("UMCSENT") or [], 92)
    if inp.G is not None and inp.G < 0 and permits_3m is not None and sentiment_3m is not None and permits_3m > 5 and sentiment_3m > 3:
        adj.append(_Adjustment("late_recession", w, "Leading indicators (permits, sentiment) turning up", "PERMIT", permits_3m))
    return adj


def _softmax(scores: dict[str, float], temperature: float) -> dict[str, float]:
    top = max(scores.values())
    exps = {k: math.exp((v - top) / temperature) for k, v in scores.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def classify_regime(
    series: Series,
    as_of: date,
    previous: Optional[dict] = None,
    prices: Optional[Series] = None,
    cfg: RegimeConfig = REGIME_CONFIG,
) -> Regime:
    """Classify the cycle phase as of `as_of`. `previous` is the last
    persisted classification ({"phase", "probabilities"}) for hysteresis."""
    inp = compute_inputs(series, as_of, prices, cfg)
    previous_phase = (previous or {}).get("phase")
    composites = {k: (round(v, 3) if v is not None else None) for k, v in
                  {"G": inp.G, "M": inp.M, "I": inp.I, "P": inp.P}.items()}

    if inp.G is None:
        return Regime(
            phase=None, probabilities={}, confidence="low",
            recession_prob_12m=_round(inp.recession_prob_12m), composites=composites,
            conflicting_signals=["Insufficient growth data to classify the cycle phase."],
            previous_phase=previous_phase, changed=False,
        )

    G, M = inp.G, inp.M or 0.0
    scores = {
        phase: cfg.base_scale * (sg * G + cfg.momentum_weight * sm * M)
        for phase, (sg, sm) in PHASE_SIGNS.items()
    }
    for a in inp.adjustments:
        scores[a.phase] += a.weight

    probs = _softmax(scores, cfg.temperature)
    ranked = sorted(probs, key=probs.get, reverse=True)
    phase = ranked[0]
    margin = probs[ranked[0]] - probs[ranked[1]]
    confidence = "high" if margin >= cfg.confidence_high else "medium" if margin >= cfg.confidence_medium else "low"
    if inp.M is None:
        confidence = "low"

    conflicts: list[str] = []
    if previous_phase in probs and previous_phase != phase and probs[phase] - probs[previous_phase] < cfg.hysteresis_margin:
        conflicts.append(
            f"Hysteresis: kept {previous_phase}; {phase} leads by only "
            f"{probs[phase] - probs[previous_phase]:.2f} (< {cfg.hysteresis_margin:.2f})."
        )
        phase = previous_phase

    drivers, against = _drivers(inp, phase, cfg)
    conflicts.extend(against)

    return Regime(
        phase=phase,
        probabilities={k: round(probs[k], 4) for k in PHASES},
        confidence=confidence,
        recession_prob_12m=_round(inp.recession_prob_12m),
        composites=composites,
        drivers=drivers,
        conflicting_signals=conflicts,
        previous_phase=previous_phase,
        changed=previous_phase is not None and previous_phase != phase,
    )


def _round(v: Optional[float], n: int = 4) -> Optional[float]:
    return round(v, n) if v is not None else None


def _drivers(inp: RegimeInputs, phase: str, cfg: RegimeConfig) -> tuple[list[Driver], list[str]]:
    sg, sm = PHASE_SIGNS[phase]
    total_w = sum(inp.growth_weights.values()) or 1.0
    contributions: list[Driver] = []

    for name, z in inp.growth_z.items():
        c = cfg.base_scale * sg * z * inp.growth_weights[name] / total_w
        contributions.append(Driver(
            indicator=COMPONENT_LABELS.get(name, name), value=_round(inp.growth_latest[name], 3),
            direction="growth_above_trend" if z > 0 else "growth_below_trend", contribution=round(c, 3),
        ))
    for name, mom in inp.growth_momentum.items():
        c = cfg.base_scale * cfg.momentum_weight * sm * mom * inp.growth_weights[name] / total_w
        contributions.append(Driver(
            indicator=COMPONENT_LABELS.get(name, name) + " - 3m momentum", value=_round(inp.growth_latest[name], 3),
            direction="growth_improving" if mom > 0 else "growth_deteriorating", contribution=round(c, 3),
        ))
    for a in inp.adjustments:
        contributions.append(Driver(
            indicator=f"{a.label} ({a.indicator})", value=_round(a.value, 3),
            direction=f"favors_{a.phase}", contribution=round(a.weight if a.phase == phase else -a.weight, 3),
        ))

    supporting = sorted([d for d in contributions if d.contribution > 0], key=lambda d: -d.contribution)
    conflicts = [
        f"{a.label} ({a.indicator}) favors {a.phase}" for a in inp.adjustments if a.phase != phase
    ]
    conflicts.extend(
        f"{d.indicator} is {d.direction.replace('_', ' ')} ({d.contribution:+.2f}), arguing against {phase}"
        for d in sorted(contributions, key=lambda d: d.contribution)
        if d.contribution < -cfg.conflict_threshold and not d.direction.startswith("favors_")
    )
    return supporting[:cfg.top_drivers], conflicts
