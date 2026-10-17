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


def test_scoring_counts_short_false_calls_flips_and_brier():
    ms = months(date(2000, 1, 1), 12)
    phases = ["late_expansion"] * 3 + ["recession"] * 2 + ["late_expansion"] * 7   # 2-month false call
    result = bt.BacktestResult(ms[0], ms[-1], calls=[(m, p, 0) for m, p in zip(ms, phases)])
    result.recession_probs = [0.0] * 12
    bt._score(result)
    assert result.false_calls == [] and result.false_call_months == 2 and result.flips == 2
    assert result.brier == 0.0 and result.brier_skill is None   # no recession months: base rate 0


def test_brier_skill_vs_base_rate():
    ms = months(date(2000, 1, 1), 4)
    result = bt.BacktestResult(ms[0], ms[-1], calls=[(m, None, y) for m, y in zip(ms, [0, 0, 1, 1])])
    result.recession_probs = [0.0, 0.0, 1.0, 1.0]
    assert result.brier_skill == 1.0           # perfect
    result.recession_probs = [0.5] * 4
    assert result.brier_skill == 0.0           # same as always forecasting the base rate


def test_baselines_are_scored_like_the_model():
    ms = months(date(2000, 1, 1), 24)
    rec = [1 if 8 <= i <= 11 else 0 for i in range(24)]
    history = {
        "USREC": [SeriesPoint(m, r) for m, r in zip(ms, rec)],
        # Sahm series published with a lag; high through the recession
        "SAHMREALTIME": [SeriesPoint(m, 0.7 if 7 <= i <= 11 else 0.1) for i, m in enumerate(ms)],
        "T10Y3M": [SeriesPoint(m, 1.0) for m in ms],
    }
    result = bt.run_backtest(history, ms[0], ms[-1], with_baselines=True)
    assert set(result.baselines) == set(bt.BASELINES)
    sahm = result.baselines["sahm"]
    assert sahm.caught == 1 and sahm.false_call_months == 0
    assert result.baselines["probit"].caught == 0          # flat positive curve: probit ~ 18%
    assert all(p is None for p in result.recession_probs)  # too little data for the model to classify


def test_objective_prefers_catches_then_fewer_false_calls():
    a = {"caught": 4, "recessions": 4, "sustained_false_calls": 1, "false_call_months": 3, "flips": 10}
    b = {**a, "sustained_false_calls": 0, "false_call_months": 9, "flips": 40}
    c = {**a, "caught": 3}
    assert max([a, b, c], key=bt.objective) is b


def test_ablation_variants_cover_every_component():
    from app.agents.market_researcher.config import REGIME_CONFIG
    from app.agents.market_researcher.regime import ADJUSTMENT_IDS

    labels = [label for label, _ in bt.ablation_variants()]
    assert labels[0] == "current config"
    assert all(f"adjustment: drop {a}" in labels for a in ADJUSTMENT_IDS)
    assert all(f"growth: drop {k}" in labels for k in REGIME_CONFIG.growth_weights)
    assert all(f"policy: drop {k}" in labels for k in REGIME_CONFIG.policy_weights)


def test_fit_calibration_recovers_known_logistic():
    import math
    import random

    random.seed(7)
    a_true, b_true = -1.0, 0.8
    probs, ys = [], []
    for _ in range(3000):
        p = random.uniform(0.01, 0.99)
        x = math.log(p / (1 - p))
        probs.append(p)
        ys.append(1 if random.random() < 1 / (1 + math.exp(-(a_true + b_true * x))) else 0)
    a, b = bt.fit_calibration(probs, ys)
    assert abs(a - a_true) < 0.15 and abs(b - b_true) < 0.15


def test_fit_calibration_is_finite_on_separable_data():
    a, b = bt.fit_calibration([1e-9] * 100 + [0.6] * 5, [0] * 100 + [1] * 5)
    assert abs(a) < 50 and abs(b) < 50


def test_config_from_expands_growth_variant():
    cfg = bt.config_from({"growth_variant": "trend", "score_smoothing": 0.5})
    assert cfg.growth_weights == bt.GROWTH_VARIANTS["trend"] and cfg.score_smoothing == 0.5
    assert cfg.growth_weights["UNRATE_NROU_GAP"] > 0 and cfg.growth_weights["UNRATE_GAP"] == 0


def test_splice_credit_uses_monthly_baa_before_daily_exists():
    history = {
        "BAA": [SeriesPoint(date(1985, 11, 1), 12.5), SeriesPoint(date(1985, 12, 1), 11.8)],
        "GS10": [SeriesPoint(date(1985, 11, 1), 10.0), SeriesPoint(date(1985, 12, 1), 9.5)],
        "BAA10Y": [SeriesPoint(date(1986, 1, 2), 2.1)],
    }
    assert [(p.date, round(p.value, 2)) for p in bt.splice_credit(history)] == [
        (date(1985, 11, 1), 2.5), (date(1985, 12, 1), 2.3), (date(1986, 1, 2), 2.1)
    ]


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
