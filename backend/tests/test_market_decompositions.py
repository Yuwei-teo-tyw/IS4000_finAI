"""Deterministic decompositions behind event explanations, checked against
hand-computed values."""
from datetime import date, timedelta

import pytest

from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.decompositions import (
    core_cpi_momentum,
    curve_front_vs_back,
    curve_shape,
    yield_real_vs_breakeven,
)
from app.agents.market_researcher.features import shift_months
from app.agents.market_researcher.schemas import Event

END = date(2026, 10, 15)


def pts(*pairs) -> list[SeriesPoint]:
    """(days before END, value) pairs -> ascending points."""
    return sorted((SeriesPoint(END - timedelta(days=d), v) for d, v in pairs), key=lambda p: p.date)


def event(eid: str) -> Event:
    return Event(id=eid, severity="notable", description="test", evidence=["DGS10"])


def test_yield_split_with_residual_over_1m():
    series = {
        "DGS10": pts((30, 4.00), (0, 4.31)),
        "DFII10": pts((30, 1.80), (0, 2.04)),
        "T10YIE": pts((30, 2.20), (0, 2.26)),
    }
    d = yield_real_vs_breakeven(series, END, event("dgs10_multi_year_high"))
    assert d["window"] == "1m" and d["end_date"] == END.isoformat()
    assert (d["nominal_change_bp"], d["real_change_bp"], d["breakeven_change_bp"], d["residual_bp"]) == (31.0, 24.0, 6.0, 1.0)
    assert d["real_share_pct"] == 80.0                                   # 24 / (24 + 6)
    assert d["description"] == ("Of the +31bp 1-month rise in the 10Y, +24bp came from real yields (DFII10) "
                                "and +6bp from breakevens (T10YIE), residual +1bp.")


def test_sharp_weekly_move_uses_1w_window():
    series = {
        "DGS10": pts((30, 4.20), (7, 4.00), (0, 4.31)),                  # +31bp in a week crosses 25bp
        "DFII10": pts((30, 2.00), (7, 1.80), (0, 2.04)),
        "T10YIE": pts((30, 2.20), (7, 2.20), (0, 2.27)),
    }
    d = yield_real_vs_breakeven(series, END, event("dgs10_sharp_move_up"))
    assert d["window"] == "1w" and d["nominal_change_bp"] == 31.0 and d["residual_bp"] == 0.0
    assert "residual" not in d["description"]


def test_dgs30_event_says_it_decomposes_the_10y():
    series = {k: pts((30, 1.0), (0, 1.1)) for k in ("DGS10", "DFII10", "T10YIE")}
    assert "no 30Y real-yield series" in yield_real_vs_breakeven(series, END, event("dgs30_multi_year_high"))["description"]


@pytest.mark.parametrize("front,back,label", [
    (10, 30, "bear steepening"), (30, 10, "bear flattening"),
    (-30, -10, "bull steepening"), (-10, -30, "bull flattening"),
    (-10, 20, "twist steepening"), (10, -20, "twist flattening"),
])
def test_curve_shapes(front, back, label):
    assert curve_shape(front, back) == label


def test_curve_front_vs_back_picks_front_by_event():
    series = {"DGS2": pts((30, 4.00), (0, 3.60)), "DGS3MO": pts((30, 4.5), (0, 4.5)), "DGS10": pts((30, 4.10), (0, 4.00))}
    d = curve_front_vs_back(series, END, event("t10y2y_uninverted"))
    assert d["front"] == "DGS2" and d["front_change_bp"] == -40.0 and d["back_change_bp"] == -10.0
    assert d["shape"] == "bull steepening" and "-40bp" in d["description"]
    assert curve_front_vs_back(series, END, event("t10y3m_inverted"))["front"] == "DGS3MO"


def test_core_cpi_momentum():
    growth = [0.002] * 21 + [0.004, 0.003, 0.005]
    d0, v, raw = date(2024, 9, 1), 300.0, [SeriesPoint(date(2024, 9, 1), 300.0)]
    for i, g in enumerate(growth, start=1):
        v *= 1 + g
        raw.append(SeriesPoint(shift_months(d0, i), v))
    d = core_cpi_momentum({"CPILFESL": raw}, END, event("core_inflation_reaccelerating"))

    assert d["mom_last_3_pct"] == [0.4, 0.3, 0.5]
    assert d["avg_mom_12m_pct"] == 0.25                                  # (9 x 0.2 + 0.4 + 0.3 + 0.5) / 12
    assert d["latest_above_avg"] is True
    assert d["annualized_3m_pct"] == round(((1.004 * 1.003 * 1.005) ** 4 - 1) * 100, 2)
    assert d["yoy_pct"] == round((1.002 ** 9 * 1.004 * 1.003 * 1.005 - 1) * 100, 2)
    assert d["end_date"] == raw[-1].date.isoformat()


def test_missing_data_returns_none():
    assert yield_real_vs_breakeven({"DGS10": pts((30, 4.0), (0, 4.3))}, END, event("dgs10_multi_year_high")) is None
    assert curve_front_vs_back({}, END, event("t10y2y_inverted")) is None
    assert core_cpi_momentum({"CPILFESL": pts((60, 300.0), (30, 301.0))}, END, event("core_inflation")) is None
    # a stale leg (no observation near the common end date) is missing data, not a guess
    stale = {"DGS10": pts((30, 4.0), (0, 4.3)), "DFII10": pts((60, 1.8), (20, 2.0)), "T10YIE": pts((30, 2.2), (0, 2.3))}
    assert yield_real_vs_breakeven(stale, END, event("dgs10_multi_year_high")) is None


def test_core_cpi_description_wording():
    raw = [SeriesPoint(shift_months(date(2024, 9, 1), i), 300 * 1.002 ** i) for i in range(25)]
    text = core_cpi_momentum({"CPILFESL": raw}, END, event("core_inflation"))["description"]
    assert "+0.20% and +0.20%; " in text and "% YoY; the latest m/m is " in text
