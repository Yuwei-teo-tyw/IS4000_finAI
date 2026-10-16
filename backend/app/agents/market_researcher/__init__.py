"""
Market researcher agent - fetches current macro, rates, market and news
data, detects notable events, classifies the economic cycle phase, and
writes a structured, cited JSON file for a main agent to synthesize later.

Primary interface is HTTP (app/endpoints/market_researcher.py); in-process
callers use `run_market_research()`. See NOTES.md for repo-specific
decisions and deviations from market_researcher_agent.md.
"""
from pathlib import Path
from typing import Optional

from app.agents.market_researcher.schemas import MarketResearchOutput, MarketResearchRequest
from app.agents.market_researcher.service import (
    MarketResearchResult,
    MarketResearchService,
    UnsupportedRegionError,
)

__all__ = [
    "MarketResearchOutput",
    "MarketResearchRequest",
    "MarketResearchResult",
    "MarketResearchService",
    "UnsupportedRegionError",
    "run_market_research",
]


async def run_market_research(
    request: MarketResearchRequest,
    *,
    out_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> MarketResearchResult:
    """Run the full pipeline once and write `<out_dir>/<run_id>.json`."""
    return await MarketResearchService(out_dir=out_dir).run(request, run_id=run_id)
