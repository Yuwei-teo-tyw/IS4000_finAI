"""
Market Researcher integration.

`get_market_analysis()` is the single integration point. In the running app (app.py calls
`use_live_registry` at start-up) it returns the newest finished Market Analysis Agent run from the
last LIVE_MAX_AGE_DAYS days, unchanged, and there is NO mock fallback: without a run the market is
UNAVAILABLE. Without a registry (bare test apps, the CLI) it returns the illustrative mock that follows
the Market Researcher's output contract (app/agents/market_researcher/market_research_output.schema.json). `fetch_market_analysis()` wraps it
with validation against that same contract and with provenance labelling, so
swapping the data source doesn't touch any portfolio logic.

The Portfolio Agent does no web scraping or market research of its own -
that is the Market Researcher's job.
"""
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.portfolio_agent.schemas.upstream import MarketResearchOutput, UpstreamResult

logger = logging.getLogger(__name__)

_MOCK_PATH = Path(__file__).parent / "mock_data" / "market_research_output.json"

# Label of the mock path. This label, not anything inside the payload, decides how the data is reported;
# use market_source() for the label in effect (LIVE once the app has registered the run store).
MARKET_ANALYSIS_SOURCE = "MOCK"
LIVE_REGION = "US"
LIVE_MAX_AGE_DAYS = 7
_live_registry = None


class LiveMarketUnavailable(RuntimeError):
    """No usable finished Market Analysis run (the message says why)."""


def use_live_registry(registry) -> None:
    """Called once at app start-up with the Market Researcher's run registry: from then on only live runs are used."""
    global _live_registry
    _live_registry = registry


def market_source() -> str:
    return "LIVE" if _live_registry is not None else MARKET_ANALYSIS_SOURCE


async def get_market_analysis(base_currency: str | None = None) -> dict[str, Any]:
    """Return the Market Researcher's output (a MarketResearchOutput) as raw JSON."""
    if _live_registry is not None:
        from datetime import datetime, timedelta, timezone
        rec = await _live_registry.latest_success(LIVE_REGION, datetime.now(timezone.utc) - timedelta(days=LIVE_MAX_AGE_DAYS))
        if rec is None:
            raise LiveMarketUnavailable(f"No finished Market Analysis run for {LIVE_REGION} in the last {LIVE_MAX_AGE_DAYS} days.")
        with open(rec.json_path or "", "r", encoding="utf-8") as f:
            return json.load(f)
    # INPUT API HERE: Replace mock market analysis with the Market Analysis Agent API response.
    # The Market Researcher lives in this backend (app/agents/market_researcher). Either:
    #   - HTTP, as the orchestrator does:
    #       GET  /agents/market-researcher/latest?region=US&max_age_minutes=60
    #       (or POST /agents/market-researcher/runs?wait=true with a MarketResearchRequest)
    #   - in-process: await request.app.state.market_research.registry.latest_success(...)
    # ...then return the run's JSON output and set MARKET_ANALYSIS_SOURCE = "LIVE".
    with open(_MOCK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def fetch_market_analysis(base_currency: str | None = None) -> UpstreamResult:
    """Retrieve + validate the Market Researcher output. Never raises: an
    upstream failure becomes status UNAVAILABLE so the service can respond with
    an explicit data-quality status instead of a 500."""
    source = market_source()
    try:
        raw = await get_market_analysis(base_currency)
    except LiveMarketUnavailable as e:
        return UpstreamResult(source=source, status="UNAVAILABLE", issues=[str(e)])
    except Exception as e:  # network/IO errors from the upstream call
        logger.warning("Market analysis retrieval failed: %s", type(e).__name__)
        return UpstreamResult(source=source, status="UNAVAILABLE", issues=["Market research could not be retrieved."])

    try:
        research = MarketResearchOutput.model_validate(raw)
    except ValidationError as e:
        logger.warning("Market research failed validation (%d errors)", e.error_count())
        return UpstreamResult(
            source=source, status="UNAVAILABLE",
            issues=[f"Market research output failed schema validation ({e.error_count()} errors)."],
        )

    issues: list[str] = []
    quality = research.quality.status if research.quality else None
    if quality == "unusable":
        # The Market Researcher's own guidance: unusable = do not quote the regime or indicators.
        return UpstreamResult(
            source=source, status="UNAVAILABLE",
            issues=["Market Researcher marked this run unusable: "
                    + ("; ".join(research.quality.issues) or "no reason given") + "."],
        )
    incomplete = quality == "degraded" or research.regime.phase is None
    if quality == "degraded":
        issues.append("Market Researcher marked this run degraded: "
                      + ("; ".join(research.quality.issues) or "no reason given") + ".")
    if research.regime.phase is None:
        issues.append("Market Researcher could not classify the economic cycle (insufficient macro data).")
    dq = research.data_quality
    if dq.failed_sources:
        issues.append(f"Market data sources that failed: {', '.join(dq.failed_sources)}.")
    if dq.stale_series:
        issues.append(f"Stale market series: {', '.join(dq.stale_series)}.")
    if base_currency and research.region != "GLOBAL":
        issues.append(
            f"Market research covers region {research.region}; the client's base currency is {base_currency}, "
            "so local market conditions are not directly covered."
        )
    return UpstreamResult(source=source, status="INCOMPLETE" if incomplete else "OK", data=research, issues=issues)
