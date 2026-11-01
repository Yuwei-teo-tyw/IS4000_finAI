"""Model SAA recommendation for one client and one bucket: context + market + products + suitability ranking."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.agents.portfolio_agent.model_saa.context import build_context
from app.agents.portfolio_agent.model_saa.library import SaaBucket, load_library
from app.agents.portfolio_agent.model_saa.schemas import SaaRecommendationResponse, WeightCheckRequest, WeightCheckResponse
from app.agents.portfolio_agent.config import get_settings
from app.agents.portfolio_agent.model_saa.llm_pick import llm_pick
from app.agents.portfolio_agent.model_saa.selection import (
    bucket_horizon, bucket_objectives, check_weights, evaluate, metrics, no_recommendation, ranked_suitable, recommend,
)
from app.agents.portfolio_agent.model_saa.sources import live_market, shelf_products

logger = logging.getLogger(__name__)


class UnknownModelError(LookupError):
    pass


async def recommend_saa(client_id: str, bucket: SaaBucket, market_registry=None, store=None, portfolio_loader=None,
                        llm_factory=None) -> SaaRecommendationResponse:
    """Raises LookupError for an unknown client; LibraryError when the library file is broken."""
    lib = load_library()
    ctx = build_context(client_id, store=store, portfolio_loader=portfolio_loader)
    market = await live_market(market_registry)
    evals, horizon, objectives = evaluate(lib, bucket, ctx)
    pick, llm_note, llm_model = None, None, None
    if no_recommendation(lib, bucket, ctx, evals) is None:
        settings = get_settings()
        pick, llm_note = await llm_pick(bucket, ctx, ranked_suitable(evals), horizon, objectives, market, settings, llm_factory)
        llm_model = settings.llm_model
    rec, none_why = recommend(lib, bucket, ctx, evals, horizon, objectives, market, pick=pick, llm_note=llm_note, llm_model=llm_model)
    # Products for every class any model in the library uses, so the PM can add a class and still see products for it.
    classes = {ac: 1.0 for e in evals for ac in e.weights} | (rec.recommended_weights if rec else {})
    products = await shelf_products(classes, ctx.risk_level, ctx.restrictions, required=set(rec.recommended_weights) if rec else set())
    _, horizon_basis = bucket_horizon(ctx, bucket)
    _, obj_basis = bucket_objectives(ctx, bucket)
    share = ctx.three_l.get(bucket)
    logger.info("SAA recommendation client=%s bucket=%s recommended=%s market=%s", client_id, bucket, rec.model_id if rec else None, market.status)
    return SaaRecommendationResponse(
        request_id=f"SAA-{client_id}-{bucket}-{uuid.uuid4().hex[:8]}", client_id=client_id, bucket=bucket,
        bucket_label=lib.bucket(bucket).label, bucket_purpose=lib.bucket(bucket).purpose,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(), library_version=lib.version,
        methodology=lib.framework.description, bucket_amount=share.amount if share else None, bucket_pct=share.pct if share else None,
        horizon_years=horizon, horizon_basis=horizon_basis, objectives=objectives, objectives_basis=obj_basis,
        client=ctx, market=market, products=products, evaluations=evals, recommendation=rec, no_recommendation_reason=none_why,
        data_status={"client_profile": "INCOMPLETE" if ctx.missing else "OK",
                     "holdings": "OK" if ctx.holdings.available else "UNAVAILABLE",
                     "market": market.status, "products": products.status})


def check_saa(client_id: str, body: WeightCheckRequest, store=None, portfolio_loader=None) -> WeightCheckResponse:
    lib = load_library()
    model = lib.model(body.bucket, body.model_id)
    if model is None:
        raise UnknownModelError(f"Model {body.model_id} is not in the {lib.bucket(body.bucket).label} library")
    ctx = build_context(client_id, store=store, portfolio_loader=portfolio_loader or (lambda _c: {"available": False, "message": "not needed"}))
    weights = {k: float(v) for k, v in body.weights.items() if float(v) != 0}
    checks = check_weights(lib, body.bucket, ctx, model, weights)
    amount = (ctx.three_l.get(body.bucket) or None)
    amt = amount.amount if amount else None
    return WeightCheckResponse(
        client_id=client_id, bucket=body.bucket, model_id=model.id, valid=not any(c.status == "FAIL" for c in checks),
        total_pct=round(sum(weights.values()), 2), checks=checks,
        metrics=metrics(lib, {k: v for k, v in weights.items() if k in lib.asset_classes}),
        amounts={k: (round(amt * v / 100, 2) if amt else None) for k, v in weights.items()})
