"""
HTTP interface for the Product Recommender agent.

    GET  /agents/product-recommender/health       liveness + data sources in use
    GET  /agents/product-recommender/shelf        the whole product shelf (fees are display-only)
    GET  /agents/product-recommender/house-view   the CIO house view, one entry per asset class
    POST /agents/product-recommender/recommend    suitability gate + ranked shortlist for one client

Proposal-only: the PS approves the list at gate G3; nothing here approves or
executes anything. The service lives on `app.state.product_recommender`;
without it (e.g. a bare test app) one is created on first use. Validation
errors on these routes never echo submitted values, which may be client
financial data (install the PM's handler with this PREFIX).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.product_recommender.house_view import HOUSE_VIEW_SOURCE, HouseViewError
from app.agents.product_recommender.schemas import (
    HouseView,
    RecommendRequest,
    RecommendResponse,
)
from app.agents.product_recommender.service import (
    ProductRecommenderService,
    ShelfUnavailable,
)
from app.agents.product_recommender.shelf import SHELF_SOURCE

PREFIX = "/agents/product-recommender"

router = APIRouter(prefix=PREFIX, tags=["product-recommender"])


def get_service(request: Request) -> ProductRecommenderService:
    service = getattr(request.app.state, "product_recommender", None)
    if service is None:
        service = ProductRecommenderService()
        request.app.state.product_recommender = service
    return service


def _house_view_or_503(service: ProductRecommenderService) -> HouseView:
    try:
        return service.house_view()
    except HouseViewError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/health")
async def health(service: ProductRecommenderService = Depends(get_service)):
    shelf = service.shelf()
    try:
        hv_as_of = service.house_view().as_of.isoformat()
    except HouseViewError:
        hv_as_of = None
    return {
        "status": "ok" if shelf.status != "UNAVAILABLE" and hv_as_of else "degraded",
        "agent": "product_recommender",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "shelf_source": SHELF_SOURCE,
        "shelf_status": shelf.status,
        "house_view_source": HOUSE_VIEW_SOURCE,
        "house_view_as_of": hv_as_of,
    }


@router.get("/shelf")
async def shelf(service: ProductRecommenderService = Depends(get_service)):
    """Every product on the shelf. Fees are included for information only."""
    res = service.shelf()
    if res.status == "UNAVAILABLE" or res.data is None:
        raise HTTPException(status_code=503, detail="The product shelf is unavailable.")
    return {"source": res.source, "status": res.status, "issues": res.issues,
            "fees_display_only": True, **res.data.model_dump(mode="json")}


@router.get("/house-view", response_model=HouseView)
async def house_view(service: ProductRecommenderService = Depends(get_service)) -> HouseView:
    return _house_view_or_503(service)


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(body: RecommendRequest, service: ProductRecommenderService = Depends(get_service)) -> RecommendResponse:
    """Gate, rank and explain products for one client. Never approves anything."""
    try:
        return service.recommend(body)
    except ShelfUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HouseViewError as e:
        raise HTTPException(status_code=503, detail=str(e))
