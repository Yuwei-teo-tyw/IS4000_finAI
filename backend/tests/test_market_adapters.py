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


# --- Tavily news ------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from app.agents.market_researcher.adapters import market_data  # noqa: E402
from app.agents.market_researcher.adapters.news import (  # noqa: E402
    RawNewsItem,
    TavilyNewsProvider,
    collect_news,
    dedupe,
    parse_published,
    parse_tavily,
)


def test_tavily_parse_fixture():
    items = parse_tavily(load_fixture("tavily_news.json"), "yields")
    assert items and all(i.url.startswith("https://") for i in items)
    assert items[0].source == "cnbc.com"
    assert items[0].published_at == datetime(2026, 10, 15, 7, 52, 47, tzinfo=timezone.utc)


def test_parse_published_formats():
    assert parse_published("2026-10-15T07:52:47Z").tzinfo is not None
    assert parse_published("garbage") is None and parse_published(None) is None


def test_tavily_search_posts_news_topic():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=load_fixture("tavily_news.json"))

    provider = TavilyNewsProvider("k", client=_client(handler), base_delay=0)
    items = run_async(provider.search("bond yields", days=3, max_results=5))
    assert items
    assert seen["topic"] == "news" and seen["days"] == 3 and seen["max_results"] == 5


def _item(title, url, hours_ago=1, snippet=""):
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    from datetime import timedelta
    return RawNewsItem(title, url, "x.com", now - timedelta(hours=hours_ago), snippet, "q")


def test_dedupe_by_url_and_similar_title():
    items = [
        _item("Treasury yields rise after CPI report", "https://a.com/1"),
        _item("Treasury yields rise after CPI report", "https://www.a.com/1/"),       # same URL
        _item("Treasury yields rise after the CPI report", "https://b.com/2"),        # near-duplicate title
        _item("Oil jumps as OPEC cuts output", "https://c.com/3"),
    ]
    assert [i.url for i in dedupe(items, 0.85)] == ["https://a.com/1", "https://c.com/3"]


class _StubNews:
    name = "Stub"

    def __init__(self, by_query, fail=()):
        self.by_query, self.fail = by_query, set(fail)

    async def search(self, query, days, max_results):
        if query in self.fail:
            raise RuntimeError("boom")
        items = list(self.by_query.get(query, []))
        for item in items:
            item.query = query  # as a real provider tags its results
        return items


def test_collect_news_filters_old_ranks_and_reports_failures():
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    provider = _StubNews({
        "inflation CPI": [_item("CPI inflation hotter than expected", "https://a.com/cpi", 2),
                          _item("Old CPI story", "https://a.com/old", 24 * 10)],
        "oil": [_item("Celebrity news", "https://b.com/celeb", 1)],
    }, fail={"broken"})
    items, failures = run_async(collect_news(provider, ["inflation CPI", "oil", "broken"], 3, 5, 10, 0.85, now=now))
    assert [i.url for i in items] == ["https://a.com/cpi", "https://b.com/celeb"]
    assert failures == ["Stub: broken"]


def test_collect_news_raises_when_every_query_fails():
    with pytest.raises(SourceError):
        run_async(collect_news(_StubNews({}, fail={"a", "b"}), ["a", "b"], 3, 5, 10, 0.85))


# --- yfinance ---------------------------------------------------------------

def test_yfinance_provider_runs_download_in_thread(monkeypatch):
    from app.agents.market_researcher.adapters.base import SeriesPoint

    def fake_download(symbols, start, end):
        return {s: [SeriesPoint(end, 1.0)] for s in symbols if s != "BAD"}

    monkeypatch.setattr(market_data, "_download_closes", fake_download)
    out = run_async(market_data.YFinanceProvider().get_histories(["SPY", "BAD"], date(2026, 1, 1), date(2026, 1, 2)))
    assert list(out) == ["SPY"]


def test_yfinance_provider_wraps_errors(monkeypatch):
    def broken(*args):
        raise KeyError("Close")

    monkeypatch.setattr(market_data, "_download_closes", broken)
    with pytest.raises(SourceError, match="yfinance"):
        run_async(market_data.YFinanceProvider().get_histories(["SPY"], date(2026, 1, 1), date(2026, 1, 2)))


def test_collect_news_boosts_priority_queries():
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    provider = _StubNews({
        "inflation CPI": [_item("CPI inflation hotter than expected", "https://a.com/cpi", 1)],
        "China economy market news": [_item("Beijing unveils stimulus", "https://b.com/china", 30)],
    })
    items, _ = run_async(collect_news(provider, ["inflation CPI", "China economy market news"], 3, 5, 1, 0.85,
                                      now=now, priority_queries=["China economy market news"]))
    assert [i.url for i in items] == ["https://b.com/china"]
