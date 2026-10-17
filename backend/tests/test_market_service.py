"""
Contract test for the market researcher pipeline: stubbed FRED / prices /
news / LLM in, a valid MarketResearchOutput JSON file out - including the
partial-failure paths the main agent relies on `data_quality` to report.
"""
import json
from datetime import date, timedelta

import pytest

import app.agents.market_researcher.news_tagging as tagging_module
from app.agents.market_researcher import config as cfg
from app.agents.market_researcher.adapters.base import SeriesPoint, SourceError
from app.agents.market_researcher.adapters.news import RawNewsItem
from app.agents.market_researcher.cache import InMemoryCache
from app.agents.market_researcher.features import shift_months
from app.agents.market_researcher.news_tagging import NewsTagBatch
from app.agents.market_researcher.schemas import SCHEMA_PATH, MarketResearchOutput, MarketResearchRequest, output_json_schema
from app.agents.market_researcher.service import MarketResearchService, UnsupportedRegionError

from conftest import FakeLLM, run_async

TODAY = date.today()
FREQ = {s.id: s.frequency for s in cfg.US_SERIES}


def synthetic_series(series_id: str, end: date) -> list[SeriesPoint]:
    """Gently trending synthetic history at the series' native frequency."""
    freq = FREQ[series_id]
    if freq in ("M", "Q"):
        step = 1 if freq == "M" else 3
        start = date(end.year - 15, 1, 1)
        dates, d = [], start
        while d <= end - timedelta(days=40):
            dates.append(d)
            d = shift_months(d, step)
    else:
        days = 1 if freq == "D" else 7
        dates = [end - timedelta(days=days * i) for i in range(int(365 * 12 / days), 0, -1)]
    base = 100.0 if freq in ("M", "Q") else 3.0
    return [SeriesPoint(d, base * (1 + 0.0002 * i)) for i, d in enumerate(dates)]


class StubFred:
    def __init__(self, fail=(), fail_all=False):
        self.fail, self.fail_all, self.calls = set(fail), fail_all, []

    async def get_series(self, series_id, start, end=None, vintage_date=None):
        self.calls.append(series_id)
        if self.fail_all or series_id in self.fail:
            raise SourceError(f"FRED:{series_id}: HTTP 500")
        points = synthetic_series(series_id, end or TODAY)
        if series_id.startswith("BAML"):  # like FRED: ICE BofA OAS only has ~3 years
            points = [p for p in points if p.date >= (end or TODAY) - timedelta(days=3 * 365)]
        return points


class StubMarket:
    name = "Stub prices"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    async def get_histories(self, symbols, start, end):
        self.calls += 1
        if self.fail:
            raise SourceError("prices down")
        return {s: [SeriesPoint(end - timedelta(days=i), 100.0 - i * 0.05) for i in range(300, -1, -1)] for s in symbols}


class StubNews:
    name = "StubNews"

    def __init__(self, fail=False):
        self.fail = fail

    async def search(self, query, days, max_results):
        if self.fail:
            raise SourceError("news down")
        from datetime import datetime, timezone
        slug = abs(hash(query)) % 10_000
        return [RawNewsItem(f"Story about {query} #{slug}", f"https://news.example/{slug}", "news.example",
                            datetime.now(timezone.utc), "snippet", query)]


def make_service(tmp_path, **kw):
    settings = cfg.load_settings()
    return MarketResearchService(
        settings=settings, cache=kw.pop("cache", InMemoryCache()), out_dir=tmp_path,
        fred=kw.pop("fred", StubFred()), market=kw.pop("market", StubMarket()), news=kw.pop("news", StubNews()),
    )


@pytest.fixture(autouse=True)
def fake_tagger(monkeypatch):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(NewsTagBatch(items=[])))


def test_run_writes_valid_json_file(tmp_path):
    result = run_async(make_service(tmp_path).run(MarketResearchRequest(focus=["energy"])))

    assert result.json_path == tmp_path / f"{result.output.run_id}.json"
    reloaded = MarketResearchOutput.model_validate_json(result.json_path.read_text())
    assert reloaded.agent == "market_researcher" and reloaded.schema_version == cfg.SCHEMA_VERSION
    assert reloaded.as_of == TODAY and reloaded.region == "US"
    assert {i.id for i in reloaded.indicators} >= {"DGS10", "T10Y3M", "UNRATE", "CPILFESL"}
    assert "USREC" not in {i.id for i in reloaded.indicators}       # backtest-only
    assert len(reloaded.market_snapshot) == len(cfg.WATCHLIST)
    assert reloaded.news and all(n.url.startswith("https://") for n in reloaded.news)
    assert reloaded.regime.recession_prob_12m is not None
    assert reloaded.narrative is None                                  # include_narrative defaults off
    assert all(i.source_url.startswith("https://") for i in reloaded.indicators)
    assert not list(tmp_path.glob(".*.tmp"))                           # atomic write left no temp file


def test_committed_schema_file_matches_model():
    assert json.loads(SCHEMA_PATH.read_text()) == output_json_schema(), (
        "Regenerate with: python -m app.agents.market_researcher.schemas"
    )


def test_short_history_is_labelled(tmp_path):
    out = run_async(make_service(tmp_path).run(MarketResearchRequest())).output
    by_id = {i.id: i for i in out.indicators}
    assert by_id["DGS10"].stats_window_years == 10.0
    assert by_id["BAMLH0A0HYM2"].stats_window_years < 3.1
    assert any(n.startswith("BAMLH0A0HYM2: percentile/z-score cover only") for n in out.data_quality.notes)
    assert not any(n.startswith("DGS10:") for n in out.data_quality.notes)


def test_regime_state_saved_only_when_fred_complete(tmp_path):
    cache = InMemoryCache()
    run_async(make_service(tmp_path, cache=cache, fred=StubFred(fail={"NFCI"})).run(MarketResearchRequest()))
    assert run_async(cache.get_regime("US")) is None            # degraded run must not move shared state

    out = run_async(make_service(tmp_path, cache=cache).run(MarketResearchRequest())).output
    state = run_async(cache.get_regime("US"))
    assert state["phase"] == out.regime.phase and state["scores"] == out.regime.scores
    assert out.regime.in_recession_prob is not None


def test_partial_fred_failure_is_reported(tmp_path):
    result = run_async(make_service(tmp_path, fred=StubFred(fail={"DGS30", "NFCI"})).run(MarketResearchRequest()))
    dq = result.output.data_quality
    assert {"FRED:DGS30", "FRED:NFCI"} <= set(dq.failed_sources)
    assert "DGS30" not in {i.id for i in result.output.indicators}


def test_total_fred_failure_still_returns_prices_and_news(tmp_path):
    result = run_async(make_service(tmp_path, fred=StubFred(fail_all=True)).run(MarketResearchRequest()))
    out = result.output
    assert any(s.startswith("FRED") for s in out.data_quality.failed_sources)
    assert out.indicators == [] and out.market_snapshot and out.news
    assert out.regime.phase is None and out.regime.confidence == "low"


def test_news_and_price_failures_keep_macro_and_regime(tmp_path):
    service = make_service(tmp_path, market=StubMarket(fail=True), news=StubNews(fail=True))
    out = run_async(service.run(MarketResearchRequest())).output
    failed = " ".join(out.data_quality.failed_sources)
    assert "Market data" in failed and "News" in failed
    assert out.indicators and out.regime.composites["G"] is not None
    assert out.news == [] and out.market_snapshot == []


def test_unsupported_region_rejected(tmp_path):
    with pytest.raises(UnsupportedRegionError):
        run_async(make_service(tmp_path).run(MarketResearchRequest(region="EU")))


def test_past_as_of_omits_news_and_uses_vintages(tmp_path):
    fred = StubFred()
    out = run_async(make_service(tmp_path, fred=fred).run(MarketResearchRequest(as_of=TODAY - timedelta(days=60)))).output
    assert out.news == []
    assert any("cannot be replayed" in n for n in out.data_quality.notes)
    assert out.as_of == TODAY - timedelta(days=60)


def test_second_run_hits_cache_and_persists_regime(tmp_path):
    cache = InMemoryCache()
    fred, market = StubFred(), StubMarket()
    service = make_service(tmp_path, cache=cache, fred=fred, market=market)

    first = run_async(service.run(MarketResearchRequest())).output
    calls_after_first = len(fred.calls)
    second = run_async(service.run(MarketResearchRequest())).output

    assert len(fred.calls) == calls_after_first and market.calls == 1    # all served from cache
    assert run_async(cache.get_regime("US"))["phase"] == first.regime.phase
    assert second.regime.previous_phase == first.regime.phase
