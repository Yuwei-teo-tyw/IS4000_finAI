"""
Contract test for the market researcher pipeline: stubbed FRED / prices /
news / LLM in, a valid MarketResearchOutput JSON file out - including the
partial-failure paths the main agent relies on `data_quality` to report.
"""
import asyncio
import dataclasses
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import app.agents.market_researcher.event_explainer as explainer_module
import app.agents.market_researcher.news_tagging as tagging_module
import app.agents.market_researcher.planner as planner_module
from app.agents.market_researcher import config as cfg
from app.agents.market_researcher import synthesis as synthesis_module
from app.agents.market_researcher.audit import InMemoryAuditLog, sha256_of
from app.agents.market_researcher.adapters.base import SeriesPoint, SourceError
from app.agents.market_researcher.adapters.news import RawNewsItem
from app.agents.market_researcher.cache import InMemoryCache
from app.agents.market_researcher.features import shift_months
from app.agents.market_researcher.news_tagging import NewsTagBatch
from app.agents.market_researcher.runs import InMemoryRunRegistry, MarketResearchRunner
from app.agents.market_researcher.schemas import (
    SCHEMA_PATH,
    MarketResearchOutput,
    MarketResearchRequest,
    QueryPlan,
    RunOrigin,
    output_json_schema,
)
from app.agents.market_researcher import tracing as tracing_module
from app.agents.market_researcher.service import (
    MarketResearchService,
    UnsupportedRegionError,
    _CachedNewsProvider,
    _raw_from_json,
    _raw_to_json,
)
from app.core.constants import CURRENT_MODEL
from app.prompts.prompt_builder import get_prompt_version

from conftest import FakeLLM, run_async

TODAY = date.today()
FREQ = {s.id: s.frequency for s in cfg.US_SERIES + cfg.EXTRA_SERIES_CATALOG}


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


def quiet_planner_and_explainer(monkeypatch, planner=None, explainer=None):
    """No real LLM for the planner / explainer: by default both fail, which
    exercises their fallbacks (heuristic plan, `unavailable` explanations).
    Each module gets its own FakeLLM so concurrent calls can't steal each
    other's queued responses."""
    planner = planner or FakeLLM(RuntimeError("no LLM in tests"))
    explainer = explainer or FakeLLM(RuntimeError("no LLM in tests"))
    monkeypatch.setattr(planner_module, "get_groq_model", lambda: planner)
    monkeypatch.setattr(explainer_module, "get_groq_model", lambda: explainer)
    return planner, explainer


@pytest.fixture(autouse=True)
def fake_tagger(monkeypatch):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(NewsTagBatch(items=[])))
    quiet_planner_and_explainer(monkeypatch)


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


# --- query planner / event explanations ---------------------------------------

OIL_PLAN = QueryPlan(intent="Oil's effect on inflation", areas=["energy", "inflation"],
                     extra_series=["DCOILWTICO", "JTSJOL"], extra_symbols=["XOP"],
                     news_queries=["oil supply cuts and gasoline prices"], rationale="test")


def test_planner_and_explainer_leave_core_outputs_identical(monkeypatch, tmp_path):
    quiet_planner_and_explainer(monkeypatch, planner=FakeLLM(OIL_PLAN))
    base = dict(query="How is oil affecting the inflation outlook?", focus=["oil"])
    off = run_async(make_service(tmp_path).run(MarketResearchRequest(**base, planning="off", explain_events=False))).output
    on = run_async(make_service(tmp_path).run(MarketResearchRequest(**base))).output

    for name in ("regime", "events", "indicators", "market_snapshot"):
        assert _dump(getattr(off, name)) == _dump(getattr(on, name)), name
    assert off.plan is None and off.planned_indicators == [] and off.event_explanations == []
    assert on.plan.plan_source == "llm"
    assert {i.id for i in on.planned_indicators} == {"DCOILWTICO", "JTSJOL"}
    assert [m.id for m in on.planned_market] == ["XOP"]
    assert any("oil supply cuts and gasoline prices" in n.title for n in on.news)   # planned query merged + ranked


def _dump(value):
    if isinstance(value, list):
        return [v.model_dump(mode="json") for v in value]
    return value.model_dump(mode="json")


def test_planned_extra_failure_does_not_make_run_partial(monkeypatch, tmp_path):
    quiet_planner_and_explainer(monkeypatch, planner=FakeLLM(OIL_PLAN))
    service = make_service(tmp_path, fred=StubFred(fail={"JTSJOL"}))
    service.settings = dataclasses.replace(service.settings, fred_api_key="test-key")

    async def scenario():
        runner = MarketResearchRunner(InMemoryRunRegistry(), service)
        record = await runner.submit(MarketResearchRequest(query="oil and inflation"))
        return await runner.wait(record.run_id, timeout=30)

    record = run_async(scenario())
    out = MarketResearchOutput.model_validate_json(open(record.json_path).read())
    assert "planned:FRED:JTSJOL" in out.data_quality.failed_sources
    assert record.status == "succeeded"
    assert any("planned extras failed" in n for n in out.data_quality.notes)
    assert [i.id for i in out.planned_indicators] == ["DCOILWTICO"]


def test_coalescing_key_includes_planning_and_explain(tmp_path):
    service = make_service(tmp_path)
    service.settings = dataclasses.replace(service.settings, fred_api_key="test-key")

    async def scenario():
        runner = MarketResearchRunner(InMemoryRunRegistry(), service)
        a = await runner.submit(MarketResearchRequest(focus=["oil"]))
        b = await runner.submit(MarketResearchRequest(focus=["oil"]))
        c = await runner.submit(MarketResearchRequest(focus=["oil"], planning="off"))
        d = await runner.submit(MarketResearchRequest(focus=["oil"], explain_events=False))
        for r in (a, c, d):
            await runner.wait(r.run_id, timeout=30)
        return a, b, c, d

    a, b, c, d = run_async(scenario())
    assert a.run_id == b.run_id and len({a.run_id, c.run_id, d.run_id}) == 3


def test_heuristic_plan_when_planner_llm_fails(tmp_path):
    out = run_async(make_service(tmp_path).run(MarketResearchRequest(focus=["housing"]))).output
    assert out.plan.plan_source == "heuristic" and "MORTGAGE30US" in {i.id for i in out.planned_indicators}
    assert any("keyword heuristic" in n for n in out.data_quality.notes)


def test_quality_report_written(tmp_path):
    out = run_async(make_service(tmp_path).run(MarketResearchRequest())).output
    assert out.quality is not None and out.quality.status in ("ok", "degraded")
    assert set(out.quality.checks) == {"consistency", "completeness", "freshness", "sources", "advice_language"}
    assert out.quality.checks["consistency"] and out.quality.checks["advice_language"]


def test_quality_unusable_without_fred(tmp_path):
    out = run_async(make_service(tmp_path, fred=StubFred(fail_all=True)).run(MarketResearchRequest())).output
    assert out.quality.status == "unusable" and not out.quality.checks["sources"]


def test_one_hanging_fred_series_keeps_the_rest(tmp_path):
    class HangingFred(StubFred):
        async def get_series(self, series_id, start, end=None, vintage_date=None):
            if series_id == "DGS10":
                await asyncio.sleep(60)
            return await super().get_series(series_id, start, end, vintage_date)

    service = make_service(tmp_path, fred=HangingFred())
    service.settings = dataclasses.replace(service.settings, source_timeout_seconds=3.0)
    output = run_async(service.run(MarketResearchRequest())).output

    assert "FRED:DGS10" in output.data_quality.failed_sources
    assert not any("timed out" in s for s in output.data_quality.failed_sources)
    assert "DGS2" in {i.id for i in output.indicators} and output.regime.phase is not None


def test_empty_fred_series_is_noted_and_not_cached(tmp_path):
    class EmptyFred(StubFred):
        async def get_series(self, series_id, start, end=None, vintage_date=None):
            points = await super().get_series(series_id, start, end, vintage_date)
            return [] if series_id == "DGS2" else points

    fred = EmptyFred()
    service = make_service(tmp_path, fred=fred)
    output = run_async(service.run(MarketResearchRequest())).output
    run_async(service.run(MarketResearchRequest()))

    assert "FRED:DGS2: no observations returned." in output.data_quality.notes
    assert fred.calls.count("DGS2") == 2 and fred.calls.count("DGS10") == 1


def test_symbols_missing_from_the_provider_are_noted(tmp_path):
    class PartialMarket(StubMarket):
        async def get_histories(self, symbols, start, end):
            histories = await super().get_histories(symbols, start, end)
            return {s: pts for s, pts in histories.items() if s != "GLD"}

    output = run_async(make_service(tmp_path, market=PartialMarket()).run(MarketResearchRequest())).output
    assert any("no prices returned for GLD" in n for n in output.data_quality.notes)


def test_empty_news_results_are_not_cached():
    class EmptyNews:
        name = "Empty"
        calls = 0

        async def search(self, query, days, max_results):
            self.calls += 1
            return []

    news = EmptyNews()
    provider = _CachedNewsProvider(news, InMemoryCache())
    run_async(provider.search("oil", 3, 5))
    run_async(provider.search("oil", 3, 5))
    assert news.calls == 2


def test_output_records_model_and_prompt_versions(tmp_path):
    output = run_async(make_service(tmp_path).run(MarketResearchRequest())).output
    assert output.llm_model == CURRENT_MODEL
    assert output.prompt_versions == {k: get_prompt_version(k) for k in cfg.PIPELINE_PROMPT_KEYS}


def traced_service(tmp_path, audit=None):
    service = make_service(tmp_path)
    service.audit = audit or InMemoryAuditLog()
    return service


def test_every_llm_stage_is_traced_with_the_run_id(monkeypatch, tmp_path):
    tagger = FakeLLM(NewsTagBatch(items=[]))
    writer = FakeLLM(RuntimeError("no LLM in tests"))
    planner, _ = quiet_planner_and_explainer(monkeypatch, planner=FakeLLM(QueryPlan(intent="oil")))
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: tagger)
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: writer)
    request = MarketResearchRequest(query="how is oil?", include_narrative=True)

    output = run_async(traced_service(tmp_path).run(request, origin=RunOrigin(channel="chat", session_id="s1"))).output

    for stage, fake in (("planner", planner), ("news_tagging", tagger), ("synthesis", writer)):
        config = fake.configs[0]
        assert config["run_name"] == f"market_researcher.{stage}"
        assert config["metadata"]["market_run_id"] == output.run_id
        assert config["metadata"]["langfuse_session_id"] == "s1"
        assert config["metadata"]["prompt_versions"]
    assert {a.stage: a.outcome for a in output.llm_attempts} == {
        "planner": "accepted", "news_tagging": "accepted", "event_explainer": "error", "synthesis": "error"}


def test_background_runs_attach_the_langfuse_handler(monkeypatch):
    monkeypatch.setattr(tracing_module, "tracing_enabled", lambda: True)
    monkeypatch.setattr(tracing_module, "get_langfuse_handler", lambda: "handler")
    with tracing_module.run_trace("mr_1"):
        config = tracing_module.trace_config("planner", ["market_researcher.planner_system"])
    assert config["callbacks"] == ["handler"] and config["metadata"]["langfuse_session_id"] == "mr_1"


def test_output_records_origin(tmp_path):
    origin = RunOrigin(channel="chat", session_id="s1", client_id="c9")
    assert run_async(traced_service(tmp_path).run(MarketResearchRequest(), origin=origin)).output.origin == origin


def test_finished_run_is_audited_with_the_files_hash(tmp_path):
    service = traced_service(tmp_path)
    result = run_async(service.run(MarketResearchRequest(), origin=RunOrigin(channel="http")))

    [event] = run_async(service.audit.events(result.output.run_id))
    assert event["event"] == "run_finished" and event["details"]["sha256"] == sha256_of(result.json_path.read_bytes())
    assert event["details"]["quality"] == result.output.quality.status


def test_failed_run_is_audited(monkeypatch, tmp_path):
    service = traced_service(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.agents.market_researcher.service.write_json_atomic", fail)
    with pytest.raises(OSError):
        run_async(service.run(MarketResearchRequest(query="rates?"), run_id="mr_failed"))

    [event] = run_async(service.audit.events("mr_failed"))
    assert event["event"] == "run_failed" and "disk full" in event["details"]["error"]
    assert event["details"]["query"] == "rates?"


def test_audit_store_failure_does_not_fail_the_run(tmp_path, caplog):
    class BrokenAudit(InMemoryAuditLog):
        async def record(self, run_id, event, details):
            raise RuntimeError("db down")

    with caplog.at_level("WARNING", logger="market_researcher"):
        result = run_async(traced_service(tmp_path, audit=BrokenAudit()).run(MarketResearchRequest()))
    assert result.json_path.is_file() and "not recorded" in caplog.text


def test_retrieved_at_survives_the_news_cache():
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    item = RawNewsItem("t", "https://x.example/a", "x.example", None, "s", "q", retrieved_at=stamp)
    assert _raw_from_json(_raw_to_json(item)).retrieved_at == stamp


def run_lines(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "market_researcher"]


def test_healthy_run_logs_only_its_start_and_finish(tmp_path, caplog):
    with caplog.at_level("INFO", logger="market_researcher"):
        output = run_async(traced_service(tmp_path).run(MarketResearchRequest(planning="off", explain_events=False))).output
    lines = run_lines(caplog)
    assert [level for level, _ in lines if level == "INFO"] == ["INFO", "INFO"]
    assert "started" in lines[0][1] and f"quality={output.quality.status}" in lines[1][1]
    assert all("quality issues" in m for level, m in lines if level == "WARNING")  # stub data trips the freshness check


def test_problems_are_logged_with_the_run_id(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(RuntimeError("no LLM in tests")))
    service = make_service(tmp_path, fred=StubFred(fail=["DGS10"]), market=StubMarket(fail=True))
    service.audit = InMemoryAuditLog()
    with caplog.at_level("INFO", logger="market_researcher"):
        run_id = run_async(service.run(MarketResearchRequest(planning="off"))).output.run_id

    warnings = [m for level, m in run_lines(caplog) if level == "WARNING"]
    assert all(run_id in m for m in warnings)
    assert any("FRED:DGS10 failed" in m for m in warnings)
    assert any("source failed: Market data" in m for m in warnings)
    assert any("stage=news_tagging" in m and "outcome=error" in m for m in warnings)
    assert any("quality issues" in m for m in warnings)


def test_failed_run_logs_an_error(monkeypatch, tmp_path, caplog):
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.agents.market_researcher.service.write_json_atomic", fail)
    with caplog.at_level("INFO", logger="market_researcher"), pytest.raises(OSError):
        run_async(traced_service(tmp_path).run(MarketResearchRequest(), run_id="mr_failed"))
    assert ("ERROR", "run=mr_failed failed: OSError: disk full") in run_lines(caplog)

