"""InMemoryCache TTL behavior and regime-state storage."""
from datetime import date

from app.agents.market_researcher import cache as cache_module
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.cache import InMemoryCache, points_from_json, points_to_json

from conftest import run_async


def test_set_get_and_expiry(monkeypatch):
    c = InMemoryCache()
    now = [1000.0]
    monkeypatch.setattr(cache_module.time, "time", lambda: now[0])

    run_async(c.set("k", {"a": 1}, ttl_seconds=60))
    assert run_async(c.get("k")) == {"a": 1}

    now[0] += 61
    assert run_async(c.get("k")) is None
    assert run_async(c.get("missing")) is None


def test_regime_state_roundtrip():
    c = InMemoryCache()
    assert run_async(c.get_regime("US")) is None
    run_async(c.set_regime("US", {"phase": "late_expansion", "probabilities": {"late_expansion": 0.6}}))
    assert run_async(c.get_regime("US"))["phase"] == "late_expansion"


def test_points_json_roundtrip():
    pts = [SeriesPoint(date(2026, 1, 1), 1.5), SeriesPoint(date(2026, 1, 2), 2.0)]
    assert points_from_json(points_to_json(pts)) == pts
