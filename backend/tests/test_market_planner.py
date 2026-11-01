"""Query planner: catalog-only validation, caps, query hygiene, and the
heuristic fallback on LLM failure / timeout / an all-invalid plan."""
import asyncio

import pytest

import app.agents.market_researcher.planner as planner_module
from app.agents.market_researcher import config as cfg
from app.agents.market_researcher.planner import heuristic_plan, make_plan, validate_plan
from app.agents.market_researcher.schemas import MarketResearchRequest, QueryPlan

from conftest import FakeLLM, run_async

CATS = (cfg.EXTRA_SERIES_CATALOG, cfg.EXTRA_SYMBOL_CATALOG)


def plan(**kw) -> QueryPlan:
    return QueryPlan(intent="Oil and inflation", areas=["energy", "inflation"], rationale="test", **kw)


def use_llm(monkeypatch, *responses) -> FakeLLM:
    llm = FakeLLM(*responses)
    monkeypatch.setattr(planner_module, "get_groq_model", lambda: llm)
    return llm


def test_catalogs_are_disjoint_from_core_and_described():
    series_ids = [s.id for s in cfg.EXTRA_SERIES_CATALOG]
    symbols = [s.symbol for s in cfg.EXTRA_SYMBOL_CATALOG]
    assert len(series_ids) == len(set(series_ids)) and len(symbols) == len(set(symbols))
    assert not set(series_ids) & {s.id for s in cfg.US_SERIES}
    assert not set(symbols) & {s.symbol for s in cfg.WATCHLIST}
    assert all(s.description and s.tags for s in cfg.EXTRA_SERIES_CATALOG + cfg.EXTRA_SYMBOL_CATALOG)


def test_valid_plan_accepted(monkeypatch):
    use_llm(monkeypatch, plan(extra_series=["DCOILWTICO", "cpiengsl"], extra_symbols=["XOP"],
                              news_queries=["oil supply cuts and gasoline prices"]))
    record, notes = run_async(make_plan(MarketResearchRequest(query="How is oil affecting inflation?")))
    assert record.plan_source == "llm" and notes == [] and record.dropped == []
    assert record.plan.extra_series == ["DCOILWTICO", "CPIENGSL"]       # case-normalized to catalog ids
    assert record.plan.extra_symbols == ["XOP"]
    assert record.latency_ms is not None


def test_invalid_items_dropped_with_reasons():
    raw = plan(
        extra_series=["MADEUP1", "DGS10", "DCOILWTICO", "DCOILWTICO"] + [s.id for s in cfg.EXTRA_SERIES_CATALOG[1:9]],
        extra_symbols=["SPY", "NOTREAL"],
        news_queries=["oil", "see https://example.com oil news today", "site:reuters oil prices news",
                      "inflation CPI report", "oil supply cuts and gasoline prices", "OPEC output decision this week",
                      "energy stocks rally on crude", "Brent spread to WTI widens", "natural gas storage report surprise"],
    )
    cleaned, dropped = validate_plan(raw, *CATS)
    text = " | ".join(dropped)
    assert "MADEUP1: not in catalog" in text and "DGS10: already in the core set" in text
    assert "DCOILWTICO: duplicate" in text and "over the cap of 8" in text
    assert "SPY: already in the core set" in text and "NOTREAL: not in catalog" in text
    assert "must be 3-12 words" in text and "contains a URL" in text and "uses a search operator" in text
    assert "'inflation CPI report': duplicates another query" in text           # a core query
    assert len(cleaned.extra_series) == cfg.PLANNER_MAX_EXTRA_SERIES and "MADEUP1" not in cleaned.extra_series
    assert cleaned.extra_symbols == []
    assert len(cleaned.news_queries) == cfg.PLANNER_MAX_NEWS_QUERIES


@pytest.mark.parametrize("failure", [RuntimeError("groq down"), "timeout", "all_invalid"])
def test_fallback_to_heuristic(monkeypatch, failure):
    if failure == "timeout":
        class Slow:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                await asyncio.sleep(5)
        monkeypatch.setattr(planner_module, "get_groq_model", lambda: Slow())
    elif failure == "all_invalid":
        use_llm(monkeypatch, plan(extra_series=["NOPE"], news_queries=["x"]))
    else:
        use_llm(monkeypatch, failure)

    request = MarketResearchRequest(query="How are mortgage rates and housing holding up?", focus=["housing"])
    record, notes = run_async(make_plan(request, budget_s=0.05))
    assert record.plan_source == "heuristic" and notes and "keyword heuristic" in notes[0]
    assert record.plan.extra_series and all(s in {c.id for c in cfg.EXTRA_SERIES_CATALOG} for s in record.plan.extra_series)
    assert "MORTGAGE30US" in record.plan.extra_series
    assert record.plan.news_queries == ["housing market news"]   # focus terms, not the raw message
    if failure == "all_invalid":
        assert any("NOPE" in d for d in record.dropped)


def test_empty_plan_is_fine(monkeypatch):
    use_llm(monkeypatch, plan())
    record, notes = run_async(make_plan(MarketResearchRequest(query="Summarize the cycle")))
    assert record.plan_source == "llm" and record.plan.extra_series == [] and notes == []


def test_no_query_or_focus_skips_without_llm(monkeypatch):
    llm = use_llm(monkeypatch)
    record, notes = run_async(make_plan(MarketResearchRequest()))
    assert record.plan_source == "skipped" and record.plan is None and llm.calls == []


def test_prompt_lists_catalogs_and_core(monkeypatch):
    llm = use_llm(monkeypatch, plan())
    run_async(make_plan(MarketResearchRequest(query="Is the labor market cooling?")))
    human = llm.calls[0][1].content
    assert "JTSJOL | JOLTS Job Openings | labor |" in human and "XHB |" in human
    assert "core series: DGS3MO" in human and "stock market today" in human


def test_heuristic_tags():
    p = heuristic_plan(MarketResearchRequest(query="Impact of a stronger yen on US markets?"), *CATS)
    assert "fx" in p.areas and "DEXJPUS" in p.extra_series and "FXY" in p.extra_symbols


def test_heuristic_only_searches_the_raw_message_without_focus_terms():
    with_focus = MarketResearchRequest(query="How is the Tan family's oil position?", focus=["oil"])
    assert heuristic_plan(with_focus, (), ()).news_queries == ["oil market news"]
    without = MarketResearchRequest(query="How is oil?")
    assert heuristic_plan(without, (), ()).news_queries == ["How is oil?"]
