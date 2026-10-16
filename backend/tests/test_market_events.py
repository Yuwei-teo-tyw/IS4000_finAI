"""Notable-event rules: each should fire on a synthetic series built to
trigger it, and stay quiet on a calm one."""
from datetime import date, timedelta

from app.agents.market_researcher import events as ev
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.config import EVENT_THRESHOLDS as T
from app.agents.market_researcher.features import shift_months

AS_OF = date(2026, 10, 16)


def daily(values, end=AS_OF):
    start = end - timedelta(days=len(values) - 1)
    return [SeriesPoint(start + timedelta(days=i), v) for i, v in enumerate(values)]


def weekly(values, end=AS_OF):
    start = end - timedelta(weeks=len(values) - 1)
    return [SeriesPoint(start + timedelta(weeks=i), v) for i, v in enumerate(values)]


def monthly(values, end=date(2026, 9, 1)):
    return [SeriesPoint(shift_months(end, i - len(values) + 1), v) for i, v in enumerate(values)]


def ids(events):
    return {e.id for e in events}


def test_yield_multi_year_high_reports_lookback():
    values = [5.3] + [4.0] * (365 * 5) + [5.4]
    events = ev.yield_highs({"DGS10": daily(values)}, {}, AS_OF, T)
    assert ids(events) == {"dgs10_high_in_history"}
    values = [5.5] + [4.0] * (365 * 3) + [5.4]
    (event,) = ev.yield_highs({"DGS10": daily(values)}, {}, AS_OF, T)
    assert event.id == "dgs10_multi_year_high" and event.severity == "notable"
    assert "3.0 years" in event.description


def test_yield_high_quiet_when_recent_high_exists():
    values = [4.0] * 400 + [4.6, 4.5]
    assert ev.yield_highs({"DGS10": daily(values)}, {}, AS_OF, T) == []


def test_sharp_yield_move():
    values = [4.0] * 40 + [4.0, 4.1, 4.2, 4.3, 4.35, 4.4, 4.45, 4.5]
    (event,) = ev.sharp_yield_move({"DGS10": daily(values)}, {}, AS_OF, T)
    assert event.id == "dgs10_sharp_move_up" and "+50bp over 1 week" in event.description
    assert ev.sharp_yield_move({"DGS10": daily([4.0] * 60)}, {}, AS_OF, T) == []


def test_curve_uninversion_after_long_inversion_is_major():
    values = [-0.5] * 400 + [0.1] * 5
    (event,) = ev.curve_crossings({"T10Y3M": daily(values)}, {}, AS_OF, T)
    assert event.id == "t10y3m_uninverted" and event.severity == "major"


def test_curve_inversion_and_still_inverted():
    assert ids(ev.curve_crossings({"T10Y2Y": daily([0.3] * 50 + [-0.1] * 3)}, {}, AS_OF, T)) == {"t10y2y_inverted"}
    assert ids(ev.curve_crossings({"T10Y2Y": daily([-0.3] * 100)}, {}, AS_OF, T)) == {"t10y2y_still_inverted"}
    assert ev.curve_crossings({"T10Y2Y": daily([0.5] * 100)}, {}, AS_OF, T) == []


def test_sahm_rule():
    assert ids(ev.sahm_rule({"SAHMREALTIME": monthly([0.2, 0.55])}, {}, AS_OF, T)) == {"sahm_rule_triggered"}
    assert ids(ev.sahm_rule({"SAHMREALTIME": monthly([0.2, 0.35])}, {}, AS_OF, T)) == {"sahm_rule_warning"}
    assert ev.sahm_rule({"SAHMREALTIME": monthly([0.1])}, {}, AS_OF, T) == []


def test_claims_rising():
    values = [200_000] * 40 + [260_000] * 8
    assert ids(ev.claims_rising({"ICSA": weekly(values)}, {}, AS_OF, T)) == {"jobless_claims_rising"}
    assert ev.claims_rising({"ICSA": weekly([200_000] * 52)}, {}, AS_OF, T) == []


def test_credit_stress():
    values = [3.0] * 300 + [4.5] * 5
    events = ev.credit_stress({"BAMLH0A0HYM2": daily(values)}, {}, AS_OF, T)
    assert ids(events) == {"credit_stress"} and events[0].severity == "major"
    assert ev.credit_stress({"BAMLH0A0HYM2": daily([3.0] * 300)}, {}, AS_OF, T) == []


def test_financial_conditions():
    assert ids(ev.financial_conditions({"NFCI": weekly([-0.5] * 20 + [0.1])}, {}, AS_OF, T)) == {"financial_conditions_tight"}
    assert ids(ev.financial_conditions({"NFCI": weekly([-0.6] * 20 + [-0.3])}, {}, AS_OF, T)) == {"financial_conditions_tightening"}
    assert ev.financial_conditions({"NFCI": weekly([-0.5] * 20)}, {}, AS_OF, T) == []


def test_inflation_reacceleration():
    flat = [100.0 * (1.02 ** (i / 12)) for i in range(16)]
    hot = flat[:13] + [flat[12] * 1.005, flat[12] * 1.010, flat[12] * 1.015]
    assert ids(ev.inflation_reacceleration({"CPILFESL": monthly(hot)}, {}, AS_OF, T)) == {"core_inflation_reaccelerating"}
    assert ev.inflation_reacceleration({"CPILFESL": monthly(flat)}, {}, AS_OF, T) == []


def test_equity_drawdown_vol_spike_oil_shock():
    spy = daily([100.0] * 200 + [85.0] * 5)
    assert ids(ev.equity_drawdown({}, {"SPY": spy}, AS_OF, T)) == {"spy_correction"}
    assert ids(ev.equity_drawdown({}, {"SPY": daily([100.0] * 200 + [75.0])}, AS_OF, T)) == {"spy_bear_market"}
    assert ev.equity_drawdown({}, {"SPY": daily([100.0] * 200)}, AS_OF, T) == []

    assert ids(ev.volatility_spike({}, {"^VIX": daily([15.0] * 20 + [32.0])}, AS_OF, T)) == {"volatility_spike"}
    # falls back to FRED VIXCLS when no price data
    assert ids(ev.volatility_spike({"VIXCLS": daily([12.0] * 20 + [20.0])}, {}, AS_OF, T)) == {"volatility_spike"}
    assert ev.volatility_spike({}, {"^VIX": daily([15.0] * 20)}, AS_OF, T) == []

    assert ids(ev.oil_shock({}, {"CL=F": daily([60.0] * 100 + [80.0])}, AS_OF, T)) == {"oil_shock"}
    assert ev.oil_shock({}, {"CL=F": daily([60.0] * 100)}, AS_OF, T) == []


def test_policy_rate_change():
    upper = daily([4.5] * 100 + [4.25] * 20)
    lower = daily([4.25] * 100 + [4.0] * 20)
    (event,) = ev.policy_rate_change({"DFEDTARU": upper, "DFEDTARL": lower}, {}, AS_OF, T)
    assert event.id == "fed_cut" and "4.00-4.25%" in event.description


def test_detect_events_sorted_by_severity_and_ignores_future_data():
    series = {
        "SAHMREALTIME": monthly([0.6]),
        "T10Y2Y": daily([-0.3] * 100),
        "NFCI": weekly([-0.5] * 20 + [0.1], end=AS_OF + timedelta(days=30)),
    }
    events = ev.detect_events(series, None, AS_OF)
    assert [e.severity for e in events] == ["major", "info"]
