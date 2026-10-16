"""
Regime backtest (guide §4.5).

The scoring logic is tested offline on synthetic calls. The full backtest
against live FRED history is opt-in - it needs FRED_API_KEY and ~30s:

    RUN_BACKTEST=1 pytest -m slow tests/test_market_regime_backtest.py
"""
import asyncio
import os
from datetime import date
from pathlib import Path

import pytest

from app.agents.market_researcher import backtest as bt
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.features import shift_months


def months(start, n):
    return [shift_months(start, i) for i in range(n)]


def test_nber_recessions_from_usrec():
    flags = [0, 0, 1, 1, 1, 0, 0, 1, 0]
    usrec = [SeriesPoint(d, v) for d, v in zip(months(date(2000, 1, 1), len(flags)), flags)]
    recs = bt.nber_recessions(usrec, date(2000, 1, 1), date(2000, 9, 1))
    assert [(r.start, r.end) for r in recs] == [
        (date(2000, 3, 1), date(2000, 5, 1)),
        (date(2000, 8, 1), date(2000, 8, 1)),
    ]


def test_scoring_catches_leads_and_false_calls():
    ms = months(date(2000, 1, 1), 48)
    usrec = {m: int(date(2001, 3, 1) <= m <= date(2001, 11, 1)) for m in ms}
    phases = {m: "late_expansion" for m in ms}
    for m in months(date(2001, 1, 1), 6):
        phases[m] = "recession"                    # 2 months early
    for m in months(date(2003, 1, 1), 4):
        phases[m] = "recession"                    # false call, >6m after the end
    for m in months(date(2002, 2, 1), 3):
        phases[m] = "early_expansion"
    result = bt.BacktestResult(ms[0], ms[-1], calls=[(m, phases[m], usrec[m]) for m in ms])
    result.recessions = bt.nber_recessions([SeriesPoint(m, usrec[m]) for m in ms], ms[0], ms[-1])
    bt._score(result)

    (rec,) = result.recessions
    assert rec.caught and rec.lead_months == -2
    assert rec.late_expansion_before and rec.early_expansion_after
    assert result.false_calls == [(date(2003, 1, 1), date(2003, 4, 1))]
    assert result.passed


def test_splice_curve_uses_monthly_spread_before_daily_exists():
    history = {
        "GS10": [SeriesPoint(date(1981, 1, 1), 12.0), SeriesPoint(date(1982, 1, 1), 14.0)],
        "TB3MS": [SeriesPoint(date(1981, 1, 1), 14.0), SeriesPoint(date(1982, 1, 1), 12.0)],
        "T10Y3M": [SeriesPoint(date(1982, 1, 4), 1.5)],
    }
    spliced = bt.splice_curve(history)
    assert [(p.date, p.value) for p in spliced] == [
        (date(1981, 1, 1), -2.0), (date(1982, 1, 1), 2.0), (date(1982, 1, 4), 1.5)
    ]


@pytest.mark.slow
@pytest.mark.skipif(not os.getenv("RUN_BACKTEST"), reason="set RUN_BACKTEST=1 (needs FRED_API_KEY)")
def test_full_backtest_meets_acceptance(tmp_path: Path):
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    result = asyncio.run(bt._main(date(1980, 1, 1), tmp_path / "report.md"))
    assert result.passed, (tmp_path / "report.md").read_text()
