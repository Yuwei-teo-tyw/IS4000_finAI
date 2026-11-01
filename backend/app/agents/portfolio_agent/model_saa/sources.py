"""
Market and product inputs for the model SAA recommendation.

Market: the newest finished Market Analysis Agent run (market_research_runs, via the runner's registry on
app.state). No run is started here (a run calls paid data and LLM services), and there is no mock fallback:
without a finished run the market is UNAVAILABLE and the PM is told so.

Products: the Product Specialist's shelf (the same one the Product Recommender uses), filtered to the
asset classes in the allocation and to products whose risk rating is within the client's risk level.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.agents.portfolio_agent.model_saa.schemas import MarketInfo, ProductItem, ProductsView
from app.agents.portfolio_agent.schemas.upstream import MarketResearchOutput

logger = logging.getLogger(__name__)
MARKET_REGION = "US"
MARKET_MAX_AGE_DAYS = 7
PRODUCTS_PER_CLASS = 3


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def live_market(registry, region: str = MARKET_REGION, max_age_days: int = MARKET_MAX_AGE_DAYS) -> MarketInfo:
    if registry is None:
        return MarketInfo(status="UNAVAILABLE", retrieved_at=_now(), issues=["The Market Analysis Agent is not running in this backend."])
    try:
        rec = await registry.latest_success(region, datetime.now(timezone.utc) - timedelta(days=max_age_days))
    except Exception as e:  # noqa: BLE001 - storage down: report, never fake
        logger.warning("Market run lookup failed: %s", type(e).__name__)
        return MarketInfo(status="UNAVAILABLE", retrieved_at=_now(), issues=["The Market Analysis Agent's run store could not be read."])
    if rec is None:
        return MarketInfo(status="UNAVAILABLE", retrieved_at=_now(), region=region,
                          issues=[f"No finished Market Analysis run for {region} in the last {max_age_days} days. "
                                  "Start one from the Market Analysis Agent (POST /agents/market-researcher/runs), then retry."])
    try:
        out = MarketResearchOutput.model_validate(json.loads(Path(rec.json_path or "").read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as e:
        logger.warning("Market run %s output unreadable: %s", rec.run_id, type(e).__name__)
        return MarketInfo(status="UNAVAILABLE", retrieved_at=_now(), run_id=rec.run_id, region=region,
                          issues=[f"The output of run {rec.run_id} could not be read or failed validation."])
    q = out.quality.status if out.quality else None
    if q == "unusable":
        return MarketInfo(status="UNAVAILABLE", retrieved_at=_now(), run_id=rec.run_id, region=region,
                          issues=["The Market Analysis Agent marked its latest run unusable."])
    issues = list(out.quality.issues) if out.quality and q == "degraded" else []
    return MarketInfo(
        status="INCOMPLETE" if q == "degraded" or out.regime.phase is None else "OK", run_id=rec.run_id, region=out.region,
        generated_at=str(out.generated_at), as_of=str(out.as_of), retrieved_at=_now(),
        regime_phase=out.regime.phase, regime_confidence=getattr(out.regime, "confidence", None),
        key_themes=list(getattr(out, "key_themes", None) or []), risks=list(getattr(out, "risks", None) or []),
        implications=dict(getattr(out, "implications", None) or {}), issues=issues)


async def shelf_products(weights: dict[str, float], risk_level: Optional[int], restrictions: Optional[str] = None,
                         required: Optional[set[str]] = None) -> ProductsView:
    """`required`: the classes the allocation actually holds; only a gap there makes the products INCOMPLETE."""
    from app.agents.portfolio_agent.upstream.product_specialist import PRODUCT_CANDIDATES_SOURCE, fetch_product_candidates
    res = await fetch_product_candidates()
    if res.status == "UNAVAILABLE" or res.data is None:
        return ProductsView(status="UNAVAILABLE", shelf_source=PRODUCT_CANDIDATES_SOURCE, issues=list(res.issues) or ["The product shelf could not be read."])
    shelf = res.data
    issues = list(res.issues)
    if PRODUCT_CANDIDATES_SOURCE != "LIVE":
        issues.append("The product shelf is the illustrative one, not the live workbook shelf.")
    by: dict[str, list[ProductItem]] = {}
    gaps = []
    for ac, w in sorted(weights.items(), key=lambda x: -x[1]):
        if w <= 0:
            continue
        cands = [p for p in shelf.products if p.asset_class == ac and (risk_level is None or p.risk_rating is None or p.risk_rating <= risk_level)]
        cands.sort(key=lambda p: (p.risk_rating or 9, -((p.historical_returns or {}).get("3y") or -99)))
        if not cands:
            if required is not None and ac not in required:
                continue
            gaps.append(f"{ac}: no product on the shelf within the client's risk level{'' if risk_level is None else f' ({risk_level})'}.")
            continue
        by[ac] = [ProductItem(
            product_id=p.product_id, product_name=p.product_name, asset_class=p.asset_class, sub_asset_class=p.sub_asset_class,
            product_type=p.product_type, currency=p.currency, risk_rating=p.risk_rating,
            return_1y_pct=(p.historical_returns or {}).get("1y"), return_3y_pct=(p.historical_returns or {}).get("3y"),
            max_drawdown_pct=p.maximum_drawdown, management_fee_pct=p.management_fee, liquidity=p.liquidity, lock_in=p.lock_in_period,
            note=None if p.risk_rating is not None else "Risk rating not available; confirm before recommending.") for p in cands[:PRODUCTS_PER_CLASS]]
    if restrictions:
        issues.append(f"Screen products against the client's restrictions before recommending: {restrictions}.")
    return ProductsView(status="INCOMPLETE" if gaps else "OK", shelf_source=PRODUCT_CANDIDATES_SOURCE,
                        as_of=str(shelf.as_of_date) if shelf.as_of_date else None, by_asset_class=by, gaps=gaps, issues=issues,
                        limitations=list(shelf.limitations)[:4])
