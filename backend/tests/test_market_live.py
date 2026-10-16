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
