"""
HTTP interface for the Portfolio Agent.

    GET  /agents/portfolio-agent/health                     liveness + data sources in use
    GET  /agents/portfolio-agent/templates                  the six SAA templates (A-F) options are built from
    POST /agents/portfolio-agent/portfolio/generate         construct, compare and explain portfolio options
    GET  /agents/portfolio-agent/portfolio/{request_id}     a previously generated proposal
    POST /agents/portfolio-agent/portfolio/{request_id}/options/{option_id}/evaluate
                                                              re-check adjusted weights + efficient frontier
    POST /agents/portfolio-agent/portfolio/combined           the 3L buckets' chosen portfolios checked together
    POST /agents/portfolio-agent/portfolio/{request_id}/ask  answer a chat question about that proposal

Proposal-only: nothing here executes trades or changes client holdings. The
service lives on `app.state.portfolio_agent`; without it - e.g. a bare test
app - one is created on first use (in-memory proposal store, no Postgres).
Validation errors on these routes never echo submitted values, which may be
client financial data (see `install_validation_handler`).
"""
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.agents.portfolio_agent.engine.adjust import EvaluationError, evaluate_weights
from app.agents.portfolio_agent.engine.buckets import LIQUIDITY_TEMPLATES
from app.agents.portfolio_agent.engine.combined import CombinedError, combine
from app.agents.portfolio_agent.engine.construction import TEMPLATES, template_growth
from app.agents.portfolio_agent.explain.chat import answer_question
from app.agents.portfolio_agent.schemas.adjust import WeightEvaluation, WeightEvaluationRequest
from app.agents.portfolio_agent.schemas.chat import PortfolioAnswer, PortfolioQuestion
from app.agents.portfolio_agent.schemas.combined import CombinedReview, CombinedReviewRequest
from app.agents.portfolio_agent.schemas.client import PortfolioGenerateRequest
from app.agents.portfolio_agent.schemas.response import PortfolioResponse
from app.agents.portfolio_agent.service import DuplicateRequestError, PortfolioService
from app.agents.portfolio_agent.upstream.market_analysis import MARKET_ANALYSIS_SOURCE
from app.agents.portfolio_agent.upstream.product_specialist import PRODUCT_CANDIDATES_SOURCE

PREFIX = "/agents/portfolio-agent"

router = APIRouter(prefix=PREFIX, tags=["portfolio-agent"])


def get_service(request: Request) -> PortfolioService:
    service = getattr(request.app.state, "portfolio_agent", None)
    if service is None:
        service = PortfolioService()
        request.app.state.portfolio_agent = service
    return service


@router.get("/health")
async def health(service: PortfolioService = Depends(get_service)):
    return {
        "status": "ok",
        "agent": "portfolio_agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_research_source": MARKET_ANALYSIS_SOURCE,
        "product_source": PRODUCT_CANDIDATES_SOURCE,
        "llm_enabled": service.settings.llm_enabled and bool(service.settings.groq_api_key),
        "llm_model": service.settings.llm_model,
        "llm_key_source": service.settings.llm_key_source,
    }


@router.get("/templates")
async def templates(bucket: Optional[str] = Query(default=None, pattern="^(liquidity|longevity|legacy)$")):
    """The SAA templates a proposal starts from, cautious first. The Liquidity bucket has its own
    (cash and short bonds); Longevity, Legacy and whole-portfolio proposals use A-F."""
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
        for t in (LIQUIDITY_TEMPLATES if bucket == "liquidity" else TEMPLATES)
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


@router.post("/portfolio/combined", response_model=CombinedReview)
async def combined_review(body: CombinedReviewRequest, service: PortfolioService = Depends(get_service)) -> CombinedReview:
    """The portfolio chosen for each 3L bucket (with any adjusted weights) checked as one client portfolio.
    Calculation only: nothing is saved, approved or executed."""
    pairs = []
    for c in body.buckets:
        proposal = service.get(c.request_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail=f"No proposal found for the {c.bucket} bucket. Run the Portfolio Agent again.")
        pairs.append((c, proposal))
    try:
        return combine(pairs, service.cma, body.client_total)
    except (CombinedError, EvaluationError) as e:
        raise HTTPException(status_code=409, detail=str(e))


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
    """Risk, return and constraint checks for an PM's adjusted asset-class weights, plus the
    efficient frontier. Calculation only: nothing is saved or approved."""
    proposal = service.get(request_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No proposal found for this request_id. Run the Portfolio Agent again.")
    try:
        return evaluate_weights(proposal, option_id, body.weights, service.cma)
    except EvaluationError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/portfolio/{request_id}/ask", response_model=PortfolioAnswer)
async def ask_about_portfolio(
    body: PortfolioQuestion,
    request_id: str = Path(pattern=r"^[A-Za-z0-9_\-.]{1,64}$"),
    service: PortfolioService = Depends(get_service),
) -> PortfolioAnswer:
    """Answer a chat question from the stored proposal (and the workspace context sent with it).
    The LLM answer is checked against the proposal's figures; otherwise a deterministic answer is returned.
    Read-only: nothing is saved, approved or executed."""
    proposal = service.get(request_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No proposal found for this request_id. Run the Portfolio Agent again.")
    return await answer_question(proposal, body, service.settings, service.cma, service.llm_factory)


def install_validation_handler(app: FastAPI, extra_prefixes: tuple[str, ...] = ()) -> None:
    """On Portfolio Agent routes (and any `extra_prefixes`, e.g. other agents
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
