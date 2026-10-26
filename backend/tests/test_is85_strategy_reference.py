"""IS-85: strategy reference table A-F (single source of truth, weights sum to 100, units, edge cases)."""
import json

import pytest

from app.agents.client_profiling import guide, strategies
from app.agents.client_profiling.store import DocumentStore

NAMES = {"A": "Fixed Income", "B": "Income", "C": "Yield", "D": "Balanced", "E": "Growth", "F": "Equities"}


def ask(q, chat=None):
    return guide.answer_guide_question(q, DocumentStore(), chat or (lambda s, u: json.dumps({"answer": ""})))


def test_six_strategies_and_weights_sum_to_100():
    rows = strategies.load_strategies()
    assert {r["code"]: r["name"] for r in rows} == NAMES
    for r in rows:
        assert list(r["allocation"]) == ["Bonds", "Liquidity", "Alternative Investments", "Equities", "Other"]
        assert sum(r["allocation"].values()) == 100
    assert strategies.strategy_table_error() is None


def test_units_shown():
    line = strategies.strategy_line(strategies.get_strategy("C"))
    assert "expected return 3.5% p.a." in line and "volatility 7.0% p.a." in line
    assert "max drawdown -25%" in line and "longest drawdown 48 months" in line


@pytest.mark.parametrize("q", ["Show me strategy c", "Show me Strategy C"])
def test_case_insensitive_code(q):
    r = ask(q)
    assert r["status"] == "ok" and "C Yield" in r["text"] and "Source: Strategy table" in r["text"]


def test_strategy_g_does_not_exist():
    r = ask("What is Strategy G?")
    assert r["status"] == "cannot_answer" and "Only strategies A to F exist" in r["text"]


def test_missing_metric_named_not_invented():
    s = dict(strategies.get_strategy("D"))
    del s["volatility_pct"]
    assert "volatility not available for Strategy D" in strategies.strategy_line(s)


def test_unreadable_data_says_unavailable(monkeypatch):
    def boom():
        raise OSError("gone")
    monkeypatch.setattr(strategies, "load_strategies", boom)
    r = ask("Show me strategy C")
    assert r["status"] == "unavailable" and "unavailable" in r["text"] and "%" not in r["text"]


def test_bad_weights_flagged(monkeypatch):
    rows = json.loads(json.dumps(strategies.load_strategies()))
    rows[0]["allocation"]["Bonds"] = 90
    monkeypatch.setattr(strategies, "load_strategies", lambda: rows)
    assert strategies.strategy_table_error() == "weights A"
