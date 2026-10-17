"""
Deterministic decompositions behind event explanations: small, code-computed
"why" facts the explainer LLM can cite but cannot invent - e.g. how much of
a 10Y yield move came from real yields vs breakevens.

Pure functions over the core series, no I/O. Each returns a dict of rounded
numbers plus a one-line `description` built here, or None when the data is
missing. All series in one decomposition are read at the same end date and
the same past target date (features.point_near tolerances).
"""
import statistics
from datetime import date, timedelta
from typing import Callable, Optional

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import EVENT_THRESHOLDS
from app.agents.market_researcher.schemas import Event

Series = dict[str, list[SeriesPoint]]
_WINDOW_LABELS = {7: ("1w", "1-week"), 30: ("1m", "1-month")}
_END_TOLERANCE_DAYS = 5


def _deltas(series: Series, ids: tuple[str, ...], as_of: date, days: int) -> Optional[tuple[date, dict[str, float]]]:
    """Change of each series over `days`, all measured from one common end date."""
    pts = {sid: f.truncate(series.get(sid) or [], as_of) for sid in ids}
    if any(len(p) < 2 for p in pts.values()):
        return None
    end = min(p[-1].date for p in pts.values())
    out = {}
    for sid, p in pts.items():
        last = f.value_at_or_before(p, end)
        if last is None or (end - last.date).days > _END_TOLERANCE_DAYS:
            return None
        past = f.point_near(p, end - timedelta(days=days), max(5, int(days * 0.25)), before=last.date)
        if past is None:
            return None
        out[sid] = last.value - past.value
    return end, out


def _yield_window(series: Series, as_of: date, event: Event) -> int:
    """The window that triggered the event: 1w for a sharp weekly move, else 1m."""
    if event.id.startswith("dgs10_sharp_move"):
        weekly = f.change_over(f.truncate(series.get("DGS10") or [], as_of), 7)
        if weekly is not None and abs(weekly) > EVENT_THRESHOLDS.yield_move_1w:
            return 7
    return 30


def yield_real_vs_breakeven(series: Series, as_of: date, event: Event) -> Optional[dict]:
    """ΔDGS10 ≈ ΔDFII10 (real yield) + ΔT10YIE (breakeven), in bp."""
    days = _yield_window(series, as_of, event)
    found = _deltas(series, ("DGS10", "DFII10", "T10YIE"), as_of, days)
    if found is None:
        return None
    end, d = found
    nominal, real, breakeven = (d[k] * 100 for k in ("DGS10", "DFII10", "T10YIE"))
    residual = nominal - (real + breakeven)
    explained = real + breakeven
    real_share = real / explained * 100 if abs(explained) > 1e-9 else None
    label, words = _WINDOW_LABELS[days]
    move = "rise" if nominal >= 0 else "fall"
    description = (
        f"Of the {nominal:+.0f}bp {words} {move} in the 10Y, {real:+.0f}bp came from real yields (DFII10) "
        f"and {breakeven:+.0f}bp from breakevens (T10YIE)"
        + (f", residual {residual:+.0f}bp" if abs(residual) >= 0.5 else "") + "."
    )
    if event.id.startswith("dgs30_"):
        description += " (10Y decomposition; there is no 30Y real-yield series in the core set.)"
    return {
        "name": "yield_real_vs_breakeven", "window": label, "end_date": end.isoformat(),
        "nominal_change_bp": round(nominal, 1), "real_change_bp": round(real, 1),
        "breakeven_change_bp": round(breakeven, 1), "residual_bp": round(residual, 1),
        "real_share_pct": round(real_share, 0) if real_share is not None else None,
        "description": description,
    }


def curve_shape(front_bp: float, back_bp: float) -> str:
    if front_bp >= 0 and back_bp >= 0:
        return "bear steepening" if back_bp > front_bp else "bear flattening"
    if front_bp <= 0 and back_bp <= 0:
        return "bull steepening" if front_bp < back_bp else "bull flattening"
    return "twist steepening" if back_bp > front_bp else "twist flattening"


def curve_front_vs_back(series: Series, as_of: date, event: Event) -> Optional[dict]:
    """Front (2Y for 10Y-2Y events, 3M for 10Y-3M) vs back (10Y) moves over the crossing window."""
    front = "DGS2" if event.id.startswith("t10y2y") else "DGS3MO"
    front_label = "2Y" if front == "DGS2" else "3M"
    days = EVENT_THRESHOLDS.curve_cross_window_days
    found = _deltas(series, (front, "DGS10"), as_of, days)
    if found is None:
        return None
    end, d = found
    front_bp, back_bp = d[front] * 100, d["DGS10"] * 100
    shape = curve_shape(front_bp, back_bp)
    return {
        "name": "curve_front_vs_back", "window": f"{days}d", "end_date": end.isoformat(),
        "front": front, "front_change_bp": round(front_bp, 1), "back": "DGS10", "back_change_bp": round(back_bp, 1),
        "shape": shape,
        "description": (f"Over {days} days the {front_label} yield ({front}) moved {front_bp:+.0f}bp and the 10Y "
                        f"(DGS10) {back_bp:+.0f}bp: {shape}."),
    }


def core_cpi_momentum(series: Series, as_of: date, event: Event) -> Optional[dict]:
    """Recent core CPI m/m prints vs the 12-month average m/m, and 3m annualized vs YoY."""
    raw = f.truncate(series.get("CPILFESL") or [], as_of)
    if len(raw) < 14:
        return None
    mom = [(b.value / a.value - 1) * 100 for a, b in zip(raw, raw[1:]) if a.value > 0]
    ann, yoy = f.annualized_series(raw, 3, 12), f.yoy_series(raw, "M")
    if len(mom) < 12 or not ann or not yoy or ann[-1].date != yoy[-1].date:
        return None
    last3 = [round(v, 2) for v in mom[-3:]]
    avg12 = statistics.fmean(mom[-12:])
    above = mom[-1] > avg12
    latest = raw[-1].date
    return {
        "name": "core_cpi_momentum", "window": "3m", "end_date": latest.isoformat(),
        "mom_last_3_pct": last3, "annualized_3m_pct": round(ann[-1].value, 2), "yoy_pct": round(yoy[-1].value, 2),
        "avg_mom_12m_pct": round(avg12, 2), "latest_above_avg": above,
        "description": (
            f"Core CPI (CPILFESL) m/m changes in the last three months to {latest}: {last3[0]:+.2f}%, "
            f"{last3[1]:+.2f}% and {last3[2]:+.2f}%; {ann[-1].value:.2f}% 3-month annualized vs "
            f"{yoy[-1].value:.2f}% YoY; the latest m/m is {'above' if above else 'at or below'} its 12-month average of {avg12:.2f}%."
        ),
    }


DECOMPOSITIONS: dict[str, Callable[[Series, date, Event], Optional[dict]]] = {
    "yield_real_vs_breakeven": yield_real_vs_breakeven,
    "curve_front_vs_back": curve_front_vs_back,
    "core_cpi_momentum": core_cpi_momentum,
}
