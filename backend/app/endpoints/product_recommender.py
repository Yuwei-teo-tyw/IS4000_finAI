"""
HTTP interface for the Product Recommender agent.

    GET  /agents/product-recommender/health       liveness + data sources in use
    GET  /agents/product-recommender/shelf        the whole product shelf (fees are display-only)
    GET  /agents/product-recommender/house-view   the CIO house view, one entry per asset class
    POST /agents/product-recommender/recommend    suitability gate + ranked shortlist for one client
    GET  /agents/product-recommender/asset-class-views                 CIO and agent stance for all 7 classes
    GET  /agents/product-recommender/asset-class-views/{asset_class}   full agent view on one class
    POST /agents/product-recommender/asset-class-views/{asset_class}   the same, plus a client lens

Proposal-only: the PS approves the list at gate G3; nothing here approves or
executes anything. The service lives on `app.state.product_recommender`;
without it (e.g. a bare test app) one is created on first use. Validation
errors on these routes never echo submitted values, which may be client
financial data (install the PM's handler with this PREFIX).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from app.agents.product_recommender.asset_views.schemas import (
    AssetClassHeadline,
    AssetClassView,
    AssetClassViewRequest,
)
from app.agents.product_recommender.house_view import HOUSE_VIEW_SOURCE, HouseViewError
from app.agents.product_recommender.schemas import (
    HouseView,
    RecommendRequest,
    RecommendResponse,
)
from app.agents.product_recommender.service import (
    ProductRecommenderService,
    ShelfUnavailable,
    UnknownAssetClass,
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


@router.get("/asset-class-views", response_model=list[AssetClassHeadline])
async def asset_class_headlines(service: ProductRecommenderService = Depends(get_service)) -> list[AssetClassHeadline]:
    try:
        return await service.asset_class_headlines()
    except HouseViewError as e:
        raise HTTPException(status_code=503, detail=str(e))


async def _view(service: ProductRecommenderService, asset_class: str, body: AssetClassViewRequest | None = None) -> AssetClassView:
    try:
        if body is None:
            return await service.asset_class_view(asset_class)
        return await service.asset_class_view(asset_class, body.client_id, body.client_profile)
    except UnknownAssetClass:
        raise HTTPException(status_code=404, detail="Unknown asset class.")
    except HouseViewError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/asset-class-views/{asset_class}", response_model=AssetClassView)
async def asset_class_view(asset_class: str = Path(max_length=40),
                           service: ProductRecommenderService = Depends(get_service)) -> AssetClassView:
    """The agent's own view on one asset class, beside the CIO's. Analysis for the PS, never the house view."""
    return await _view(service, asset_class)


@router.post("/asset-class-views/{asset_class}", response_model=AssetClassView)
async def asset_class_view_for_client(body: AssetClassViewRequest, asset_class: str = Path(max_length=40),
                                      service: ProductRecommenderService = Depends(get_service)) -> AssetClassView:
    """The same view with a client lens: which products and segments this client can access."""
    return await _view(service, asset_class, body)
