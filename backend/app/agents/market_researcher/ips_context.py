"""
The IPS's market environment block, from the Market Analysis Agent.

Called when the RM generates an IPS: the newest finished run from the last `IPS_MARKET_MAX_AGE_HOURS` is reused;
otherwise one run is started and awaited (same runner and run store as POST /agents/market-researcher/runs). The run
is kept small: fixed core data set (planning off), no event explanations and no narrative, so it makes as few LLM
calls as possible. Only the run's own figures and text are copied into the block; nothing is added or estimated.
A failure returns an "unavailable" block with the reason; the IPS is never given placeholder market data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from app.agents.market_researcher.schemas import MarketResearchOutput, MarketResearchRequest

logger = logging.getLogger(__name__)

IPS_MARKET_MAX_AGE_HOURS = 24
IPS_MARKET_REGION = "US"
IPS_MARKET_REQUEST = MarketResearchRequest(query="Macro backdrop for an Investment Policy Statement", region=IPS_MARKET_REGION,
                                           planning="off", explain_events=False, include_narrative=False)
# Indicator categories shown in the IPS, in this order; at most PER_CATEGORY each.
CATEGORIES = ("inflation", "rates", "growth", "labor", "credit")
PER_CATEGORY = 2
MAX_INDICATORS = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def unavailable(message: str, run_id: Optional[str] = None) -> dict:
    return {"status": "unavailable", "source": "Market Analysis Agent", "runId": run_id, "retrievedAt": _now(), "message": message}


def ips_market_block(out: MarketResearchOutput, reused: bool) -> dict:
    inds = []
    for cat in CATEGORIES:
        for i in [x for x in out.indicators if x.category == cat][:PER_CATEGORY]:
            if len(inds) < MAX_INDICATORS:
                inds.append({"name": i.name, "value": i.value, "unit": i.unit, "date": str(i.observation_date),
                             "change1y": (i.changes or {}).get("1y"), "signal": getattr(i, "signal", None), "stale": bool(getattr(i, "stale", False))})
    q = out.quality.status if out.quality else "ok"
    return {
        "status": "degraded" if q == "degraded" or out.regime.phase is None else "ok",
        "source": "Market Analysis Agent", "runId": out.run_id, "region": out.region, "asOf": str(out.as_of),
        "generatedAt": out.generated_at.isoformat(), "retrievedAt": _now(), "reusedRun": reused,
        "regime": {"phase": out.regime.phase, "confidence": out.regime.confidence, "recessionProbability": out.regime.in_recession_prob},
        "indicators": inds, "themes": list(out.key_themes or [])[:5], "risks": list(out.risks or [])[:4],
        "implications": dict(out.implications or {}),
        "notes": (list(out.quality.issues) if out.quality and q == "degraded" else [])
                 + ([f"Sources that failed: {', '.join(out.data_quality.failed_sources)}"] if out.data_quality.failed_sources else []),
    }


def _read(record) -> MarketResearchOutput:
    return MarketResearchOutput.model_validate(json.loads(Path(record.json_path or "").read_text(encoding="utf-8")))


async def ensure_market_run(runner: Any, max_age_hours: int = IPS_MARKET_MAX_AGE_HOURS, purpose: str = "IPS generation"):
    """(record, reused, None) for a finished run from the last `max_age_hours` (one is started and awaited when there is
    none), or (None, False, reason). Never raises. Used by Generate IPS and the review pack, so both read the same run."""
    if runner is None:
        return None, False, "The Market Analysis Agent is not running in this backend."
    from app.agents.market_researcher.runs import MissingConfigurationError, QueueFullError
    try:
        rec = await runner.registry.latest_success(IPS_MARKET_REGION, datetime.now(timezone.utc) - timedelta(hours=max_age_hours))
        if rec is not None:
            return rec, True, None
        started = await runner.submit(IPS_MARKET_REQUEST)
        logger.info("%s started market run %s", purpose, started.run_id)
        rec = await runner.wait(started.run_id, timeout=runner.service.settings.run_budget_seconds + 60) or started
        if rec.status not in ("succeeded", "partial"):
            return None, False, f"The market run {rec.run_id} did not finish ({rec.status}{': ' + rec.error if rec.error else ''})."
        return rec, False, None
    except MissingConfigurationError as e:
        return None, False, f"The Market Analysis Agent is not configured: {e}."
    except QueueFullError:
        return None, False, "The Market Analysis Agent is busy; try again in a minute."
    except Exception as e:  # noqa: BLE001 - network, storage: report, never fake
        logger.warning("%s market run failed: %s", purpose, type(e).__name__)
        return None, False, f"The Market Analysis Agent failed ({type(e).__name__})."


async def ips_market_context(runner: Any, max_age_hours: int = IPS_MARKET_MAX_AGE_HOURS) -> dict:
    """Never raises: every failure becomes an "unavailable" block that says why."""
    rec, reused, why = await ensure_market_run(runner, max_age_hours)
    if rec is None:
        return unavailable(why or "No market run is available.")
    try:
        return ips_market_block(_read(rec), reused)
    except (OSError, json.JSONDecodeError, ValidationError):
        return unavailable("The market run's output could not be read.")
    except Exception as e:  # noqa: BLE001 - network, storage: report, never fake
        logger.warning("IPS market context failed: %s", type(e).__name__)
        return unavailable(f"The Market Analysis Agent failed ({type(e).__name__}).")
