"""
Market researcher feature transforms - hand-computed expectations on small
synthetic series.
"""
from datetime import date, timedelta

import pytest

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import SeriesSpec


def monthly(values, start=date(2020, 1, 1)):
    return [SeriesPoint(f.shift_months(start, i), v) for i, v in enumerate(values)]


def daily(values, start=date(2024, 1, 1)):
    return [SeriesPoint(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_shift_months_clamps_day():
    assert f.shift_months(date(2024, 3, 31), -1) == date(2024, 2, 29)
    assert f.shift_years(date(2024, 2, 29), -1) == date(2023, 2, 28)


def test_yoy_series_monthly():
    pts = monthly([100.0] * 12 + [103.0])
    yoy = f.yoy_series(pts, "M")
    assert len(yoy) == 1
    assert yoy[0].date == date(2021, 1, 1)
    assert yoy[0].value == pytest.approx(3.0)


def test_annualized_3m():
    pts = monthly([100.0, 100.5, 101.0, 101.0 * 1.0])
    # (101 / 100) ** 4 - 1 = 4.0604%
    ann = f.annualized_series(pts, 3, 12)
    assert ann[-1].value == pytest.approx(((101 / 100) ** 4 - 1) * 100)


def test_diff_avg_series_payrolls():
    pts = monthly([1000.0, 1100.0, 1250.0, 1300.0])
    assert f.diff_avg_series(pts, 3)[-1].value == pytest.approx(100.0)


def test_change_over_uses_prior_observation_not_latest():
    # Friday -> Monday: the 1d change compares against Friday.
    pts = [SeriesPoint(date(2026, 10, 9), 4.0), SeriesPoint(date(2026, 10, 12), 4.1)]
    assert f.change_over(pts, 1) == pytest.approx(0.1)


def test_change_over_missing_when_history_too_short():
    pts = daily([1.0, 2.0])
    assert f.change_over(pts, 365) is None


def test_zscore_and_percentile():
    pts = daily([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    # mean 5.5, population stdev sqrt(8.25)
    assert f.zscore(pts, None) == pytest.approx((10 - 5.5) / 8.25 ** 0.5)
    assert f.percentile(pts, None) == pytest.approx(100.0)
    assert f.zscore(pts[:5], None) is None  # below min_points


def test_highest_since_and_record():
    pts = daily([5.0, 3.0, 4.0, 4.5])
    ext = f.highest_since(pts)
    assert ext.since == pts[0].date
    assert ext.years == pytest.approx(3 / 365.25)

    record = f.highest_since(daily([1.0, 2.0, 3.0]))
    assert record.since is None and record.history_start == date(2024, 1, 1)


def test_moving_average_series():
    ma = f.moving_average_series(daily([1.0, 2.0, 3.0, 4.0, 5.0]), 4)
    assert [p.value for p in ma] == [2.5, 3.5]


def test_is_stale():
    assert f.is_stale("D", date(2026, 10, 1), date(2026, 10, 16))
    assert not f.is_stale("M", date(2026, 9, 1), date(2026, 10, 16))


def test_compute_indicator_features_yoy_and_signal():
    spec = SeriesSpec("CPILFESL", "Core CPI", "%", "M", "inflation", "yoy", "inflationary", "disinflationary", "3m", 0.15)
    # flat for a year, then prices accelerate
    values = [100.0] * 13 + [100.3, 100.7, 101.2, 101.8]
    feats = f.compute_indicator_features(spec, monthly(values), as_of=date(2021, 6, 1))
    assert feats.observation_date == date(2021, 5, 1)
    assert feats.value == pytest.approx(1.8)
    assert feats.changes["3m"] == pytest.approx(1.8 - 0.3)  # YoY in Feb 2021 was 0.3%
    assert feats.annualized_3m == pytest.approx(((101.8 / 100.3) ** 4 - 1) * 100)
    assert f.signal_for(feats) == "inflationary"


def test_compute_indicator_features_respects_as_of():
    spec = SeriesSpec("DGS10", "10Y", "%", "D", "rates")
    feats = f.compute_indicator_features(spec, daily([1.0, 2.0, 3.0]), as_of=date(2024, 1, 2))
    assert feats.value == 2.0
