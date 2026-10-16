"""
Market researcher data adapters, with HTTP mocked via httpx.MockTransport
(no live calls) and recorded fixtures in tests/fixtures/market_researcher/.
"""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.agents.market_researcher.adapters.base import SourceError
from app.agents.market_researcher.adapters.fred import FredClient, parse_observations

from conftest import run_async

FIXTURES = Path(__file__).parent / "fixtures" / "market_researcher"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- FRED -------------------------------------------------------------------

def test_fred_parse_drops_missing_dot_values():
    points = parse_observations(load_fixture("fred_dgs10.json"))
    assert len(points) == 10  # 11 observations, one "."
    assert points[0].date == date(2026, 9, 1)
    assert points[-1].value == pytest.approx(5.0)


def test_fred_get_series_sends_params_and_vintage():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=load_fixture("fred_dgs10.json"))

    fred = FredClient("test-key", client=_client(handler), base_delay=0)
    points = run_async(fred.get_series("DGS10", date(2026, 9, 1), date(2026, 9, 15), vintage_date=date(2026, 9, 16)))

    assert len(points) == 10
    assert seen["series_id"] == "DGS10"
    assert seen["observation_end"] == "2026-09-15"
    assert seen["realtime_start"] == seen["realtime_end"] == "2026-09-16"


def test_fred_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json=load_fixture("fred_dgs10.json"))

    fred = FredClient("test-key", client=_client(handler), base_delay=0)
    assert run_async(fred.get_series("DGS10", date(2026, 9, 1)))
    assert calls["n"] == 3


def test_fred_does_not_retry_client_errors():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"error_message": "Bad Request. The series does not exist."})

    fred = FredClient("test-key", client=_client(handler), base_delay=0)
    with pytest.raises(SourceError):
        run_async(fred.get_series("NOPE", date(2026, 9, 1)))
    assert calls["n"] == 1


def test_fred_gives_up_after_retries_on_5xx():
    def handler(request):
        return httpx.Response(503)

    fred = FredClient("test-key", client=_client(handler), retries=2, base_delay=0)
    with pytest.raises(SourceError, match="3 attempts"):
        run_async(fred.get_series("DGS10", date(2026, 9, 1)))


def test_fred_requires_key():
    with pytest.raises(ValueError):
        FredClient("")
