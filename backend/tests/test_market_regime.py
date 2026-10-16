"""Cycle phase classifier: one synthetic scenario per phase, probability
sanity, hysteresis, and the NY Fed probit."""
from datetime import date

import pytest

from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import RegimeConfig
from app.agents.market_researcher.features import shift_months
from app.agents.market_researcher.regime import classify_regime, recession_probability

START = date(2010, 1, 1)
MONTHS = 156
AS_OF = shift_months(START, MONTHS)


def level_path(tail_rates):
    """Monthly index growing 2%/yr, with the final months following
    `tail_rates` (annual % growth per month, oldest first)."""
    rates = [2.0] * (MONTHS - len(tail_rates)) + list(tail_rates)
    level, out = 100.0, []
    for i, r in enumerate(rates):
        level *= 1 + r / 1200
        out.append(SeriesPoint(shift_months(START, i), level))
    return out


def scenario(tail_rates):
    activity = level_path(tail_rates)
    return {
        "INDPRO": activity,
        "RSAFS": [SeriesPoint(p.date, p.value * 5) for p in activity],
        "CPIAUCSL": level_path([]),
    }


SCENARIOS = {
    "early_expansion": [6.0] * 12,
    "late_expansion": [6.0] * 12 + [0.0] * 6,
    "recession": [-6.0] * 12,
    "late_recession": [-6.0] * 12 + [6.0] * 4,
}


@pytest.mark.parametrize("expected,tail", list(SCENARIOS.items()))
def test_each_phase_scenario(expected, tail):
    regime = classify_regime(scenario(tail), AS_OF)
    assert regime.phase == expected
    assert sum(regime.probabilities.values()) == pytest.approx(1.0, abs=1e-3)
    assert max(regime.probabilities, key=regime.probabilities.get) == expected
    assert regime.drivers and all(d.contribution > 0 for d in regime.drivers)
    assert set(regime.composites) == {"G", "M", "I", "P"}


def test_insufficient_data_returns_no_phase():
    regime = classify_regime({"INDPRO": level_path([])}, AS_OF)
    assert regime.phase is None and regime.confidence == "low"
    assert regime.conflicting_signals


def test_hysteresis_keeps_previous_phase_within_margin():
    series = scenario(SCENARIOS["early_expansion"])
    sticky = RegimeConfig(hysteresis_margin=1.0)
    kept = classify_regime(series, AS_OF, previous={"phase": "late_expansion"}, cfg=sticky)
    assert kept.phase == "late_expansion" and kept.changed is False
    assert any("Hysteresis" in c for c in kept.conflicting_signals)

    switched = classify_regime(series, AS_OF, previous={"phase": "late_expansion"}, cfg=RegimeConfig(hysteresis_margin=0.0))
    assert switched.phase == "early_expansion" and switched.changed is True
    assert switched.previous_phase == "late_expansion"


def test_recession_adjustments_show_as_conflicts_or_drivers():
    series = scenario(SCENARIOS["early_expansion"])
    series["SAHMREALTIME"] = [SeriesPoint(shift_months(AS_OF, -1), 0.6)]
    regime = classify_regime(series, AS_OF)
    assert any("Sahm rule" in c for c in regime.conflicting_signals) or regime.phase == "recession"


def test_probit_matches_ny_fed_formula():
    flat = [SeriesPoint(shift_months(START, i), 0.0) for i in range(24)]
    assert recession_probability({"T10Y3M": flat}, shift_months(START, 24)) == pytest.approx(0.2969, abs=1e-3)
    inverted = [SeriesPoint(p.date, -1.0) for p in flat]
    assert recession_probability({"T10Y3M": inverted}, shift_months(START, 24)) == pytest.approx(0.5397, abs=1e-3)
    assert recession_probability({}, AS_OF) is None
