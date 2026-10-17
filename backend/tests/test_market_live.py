"""
Live smoke test - real FRED / yfinance / Tavily / Groq calls. Opt-in:

    RUN_LIVE_MARKET_TESTS=1 pytest -m live tests/test_market_live.py
"""
import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("RUN_LIVE_MARKET_TESTS"), reason="set RUN_LIVE_MARKET_TESTS=1 (needs API keys)"),
]


def test_live_run(tmp_path):
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    from app.agents.market_researcher import MarketResearchRequest, MarketResearchService
    from app.agents.market_researcher.cache import InMemoryCache

    result = asyncio.run(
        MarketResearchService(cache=InMemoryCache(), out_dir=tmp_path).run(MarketResearchRequest(focus=["rates"]))
    )
    out = result.output

    assert result.json_path.is_file()
    assert not [s for s in out.data_quality.failed_sources if s.startswith("FRED")]
    ids = {i.id for i in out.indicators}
    assert {"DGS10", "T10Y3M", "UNRATE", "CPILFESL", "PAYEMS"} <= ids
    dgs10 = next(i for i in out.indicators if i.id == "DGS10")
    assert dgs10.observation_date >= date.today() - timedelta(days=10)
    assert {"SPY", "^VIX"} <= {m.id for m in out.market_snapshot}
    assert out.news, "expected at least some news items"
    assert out.regime.phase is not None and out.regime.recession_prob_12m is not None


def _load_env():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def test_catalog_ids_exist_on_fred():
    """Every EXTRA_SERIES_CATALOG id returns recent observations on FRED."""
    _load_env()
    from app.agents.market_researcher import config as cfg
    from app.agents.market_researcher.adapters.fred import FredClient

    async def check():
        fred = FredClient(os.environ["FRED_API_KEY"])
        start = date.today() - timedelta(days=3 * 365)

        async def latest(spec):
            try:
                pts = await fred.get_series(spec.id, start)
                return spec.id, pts[-1].date if pts else None
            except Exception as e:
                return spec.id, f"error: {e}"
        return await asyncio.gather(*(latest(s) for s in cfg.EXTRA_SERIES_CATALOG))

    stale_limit = {"D": 30, "W": 45, "M": 150, "Q": 300}
    freq = {s.id: s.frequency for s in cfg.EXTRA_SERIES_CATALOG}
    bad = [(sid, last) for sid, last in asyncio.run(check())
           if not isinstance(last, date) or (date.today() - last).days > stale_limit[freq[sid]]]
    assert not bad, f"catalog series missing or stale on FRED: {bad}"


def test_live_planned_run_with_explanations(tmp_path):
    _load_env()
    from app.agents.market_researcher import MarketResearchRequest, MarketResearchService
    from app.agents.market_researcher import config as cfg
    from app.agents.market_researcher.cache import InMemoryCache

    out = asyncio.run(MarketResearchService(cache=InMemoryCache(), out_dir=tmp_path).run(
        MarketResearchRequest(query="How is oil affecting the inflation outlook?", focus=["oil prices", "inflation"])
    )).output

    assert out.plan is not None and out.plan.plan_source in ("llm", "heuristic")
    energy = {s.id for s in cfg.EXTRA_SERIES_CATALOG if "energy" in s.tags} | {
        s.symbol for s in cfg.EXTRA_SYMBOL_CATALOG if "energy" in s.tags}
    assert energy & ({i.id for i in out.planned_indicators} | {m.id for m in out.planned_market})
    if any(e.severity != "info" for e in out.events):
        assert any(x.status != "skipped" for x in out.event_explanations)
    for x in out.event_explanations:
        assert x.status != "explained" or x.cited_urls
