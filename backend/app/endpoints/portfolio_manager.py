"""
HTTP interface for the Portfolio Manager agent.

    GET  /agents/portfolio-manager/health                     liveness + data sources in use
    GET  /agents/portfolio-manager/templates                  the six SAA templates (A-F) options are built from
    POST /agents/portfolio-manager/portfolio/generate         construct, compare and explain portfolio options
    GET  /agents/portfolio-manager/portfolio/{request_id}     a previously generated proposal
    POST /agents/portfolio-manager/portfolio/{request_id}/options/{option_id}/evaluate
                                                              re-check adjusted weights + efficient frontier

Proposal-only: nothing here executes trades or changes client holdings. The
service lives on `app.state.portfolio_manager`; without it - e.g. a bare test
app - one is created on first use (in-memory proposal store, no Postgres).
Validation errors on these routes never echo submitted values, which may be
client financial data (see `install_validation_handler`).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.agents.portfolio_manager.engine.adjust import EvaluationError, evaluate_weights
from app.agents.portfolio_manager.engine.construction import TEMPLATES, template_growth
from app.agents.portfolio_manager.schemas.adjust import WeightEvaluation, WeightEvaluationRequest
from app.agents.portfolio_manager.schemas.client import PortfolioGenerateRequest
from app.agents.portfolio_manager.schemas.response import PortfolioResponse
from app.agents.portfolio_manager.service import DuplicateRequestError, PortfolioService
from app.agents.portfolio_manager.upstream.market_analysis import MARKET_ANALYSIS_SOURCE
from app.agents.portfolio_manager.upstream.product_specialist import PRODUCT_CANDIDATES_SOURCE

PREFIX = "/agents/portfolio-manager"

router = APIRouter(prefix=PREFIX, tags=["portfolio-manager"])


def get_service(request: Request) -> PortfolioService:
    service = getattr(request.app.state, "portfolio_manager", None)
    if service is None:
        service = PortfolioService()
        request.app.state.portfolio_manager = service
    return service


@router.get("/health")
async def health(service: PortfolioService = Depends(get_service)):
    return {
        "status": "ok",
        "agent": "portfolio_manager",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_research_source": MARKET_ANALYSIS_SOURCE,
        "product_source": PRODUCT_CANDIDATES_SOURCE,
        "llm_enabled": service.settings.llm_enabled and bool(service.settings.groq_api_key),
    }


@router.get("/templates")
async def templates():
    """The SAA templates every proposal starts from, in A (cautious) to F (opportunistic) order."""
    return [
        {
            "option_id": t.option_id,
            "name": t.name,
            "objective": t.objective,
            "weights": {ac.value: w for ac, w in t.weights.items()},
            "growth_share_pct": template_growth(t),
            "min_risk_level": t.min_risk_level,
            "min_horizon_years": t.min_horizon_years,
        }
        for t in TEMPLATES
    ]


@router.post("/portfolio/generate", response_model=PortfolioResponse)
async def generate_portfolio(
    body: PortfolioGenerateRequest, service: PortfolioService = Depends(get_service)
) -> PortfolioResponse:
    """Construct and compare portfolio options for review. Never executes trades."""
    try:
        return await service.generate(body)
    except DuplicateRequestError:
        raise HTTPException(
            status_code=409,
            detail="A proposal with this request_id already exists. Use a new request_id, or GET the existing one.",
        )


@router.get("/portfolio/{request_id}", response_model=PortfolioResponse)
async def get_portfolio(
    request_id: str = Path(pattern=r"^[A-Za-z0-9_\-.]{1,64}$"),
    service: PortfolioService = Depends(get_service),
) -> PortfolioResponse:
    proposal = service.get(request_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No proposal found for this request_id.")
    return proposal


@router.post("/portfolio/{request_id}/options/{option_id}/evaluate", response_model=WeightEvaluation)
async def evaluate_adjusted_weights(
    body: WeightEvaluationRequest,
    request_id: str = Path(pattern=r"^[A-Za-z0-9_\-.]{1,64}$"),
    option_id: str = Path(pattern=r"^[A-F]$"),
    service: PortfolioService = Depends(get_service),
) -> WeightEvaluation:
    """Risk, return and constraint checks for an IC's adjusted asset-class weights, plus the
    efficient frontier. Calculation only: nothing is saved or approved."""
    proposal = service.get(request_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No proposal found for this request_id. Run the Portfolio Manager again.")
    try:
        return evaluate_weights(proposal, option_id, body.weights, service.cma)
    except EvaluationError as e:
        raise HTTPException(status_code=409, detail=str(e))


def install_validation_handler(app: FastAPI, extra_prefixes: tuple[str, ...] = ()) -> None:
    """On Portfolio Manager routes (and any `extra_prefixes`, e.g. other agents
    that take client profiles), report where and why validation failed but
    never echo the submitted values back. Other routes keep FastAPI's default.
    An app has one handler for this exception, so install it once with every prefix."""
    prefixes = (PREFIX, *extra_prefixes)

    @app.exception_handler(RequestValidationError)
    async def _handler(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith(prefixes):
            return await request_validation_exception_handler(request, exc)
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})
