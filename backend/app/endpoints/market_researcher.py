"""
HTTP interface for the market researcher agent - how a main agent
orchestrates it.

    POST /agents/market-researcher/runs            start a run (202 + run_id; ?wait=true blocks for the output)
    GET  /agents/market-researcher/runs/{run_id}   status
    GET  /agents/market-researcher/runs/{run_id}/output   the run's JSON output file
    GET  /agents/market-researcher/latest?region=US&max_age_minutes=60   freshest finished output
    GET  /agents/market-researcher/schema          JSON Schema of the output (the contract)
    GET  /agents/market-researcher/health          configured keys + storage reachability
    GET  /agents/market-researcher/articles?run_id=&url=   reader view of one cited news article (chat UI)

If MARKET_RESEARCH_API_TOKEN is set, every route except /articles requires
`Authorization: Bearer <token>` (service-to-service); unset = open, for
local dev. /articles is called by the browser and can only read articles
a run already cited (see article_reader.py), so it sits on `ui_router`
without the token. The runner lives on `app.state.market_research` (Postgres-backed,
built in app.py's lifespan); without it - e.g. a bare test app - an
in-memory runner is created on first use.
"""
import hmac
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.agents.market_researcher.article_reader import ArticleNotFoundError, read_article
from app.agents.market_researcher.cache import InMemoryCache
from app.agents.market_researcher.config import load_settings
from app.agents.market_researcher.runs import (
    FINISHED,
    InMemoryRunRegistry,
    MarketResearchRunner,
    MissingConfigurationError,
    QueueFullError,
    RunRecord,
)
from app.agents.market_researcher.schemas import MarketResearchRequest, output_json_schema
from app.agents.market_researcher.service import MarketResearchService, UnsupportedRegionError

PREFIX = "/agents/market-researcher"


def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = load_settings().api_token
    if not expected:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token",
                            headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix=PREFIX, tags=["market-researcher"], dependencies=[Depends(require_token)])
ui_router = APIRouter(prefix=PREFIX, tags=["market-researcher"])


def get_runner(request: Request) -> MarketResearchRunner:
    runner = getattr(request.app.state, "market_research", None)
    if runner is None:
        runner = MarketResearchRunner(InMemoryRunRegistry(), MarketResearchService(cache=InMemoryCache()))
        request.app.state.market_research = runner
    return runner


def _links(run_id: str) -> dict:
    return {"status_url": f"{PREFIX}/runs/{run_id}", "output_url": f"{PREFIX}/runs/{run_id}/output"}


def _status_body(record: RunRecord) -> dict:
    return {**record.model_dump(mode="json", exclude={"json_path"}), **_links(record.run_id)}


def _output_file(record: RunRecord) -> FileResponse:
    path = Path(record.json_path or "")
    if not record.json_path or not path.is_file():
        raise HTTPException(status_code=410, detail=f"Output file for run {record.run_id} is no longer available")
    return FileResponse(path, media_type="application/json", filename=path.name)


@router.post("/runs", status_code=202)
async def create_run(
    body: MarketResearchRequest,
    wait: bool = Query(default=False, description="Block until the run finishes and return its output."),
    runner: MarketResearchRunner = Depends(get_runner),
):
    try:
        record = await runner.submit(body)
    except UnsupportedRegionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except MissingConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except QueueFullError as e:
        raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": "30"})

    if wait:
        settings = runner.service.settings
        record = await runner.wait(record.run_id, timeout=settings.run_budget_seconds + 60) or record
        if record.status in ("succeeded", "partial"):
            return _output_file(record)
        if record.status == "failed":
            return JSONResponse(status_code=502, content=_status_body(record))
    return JSONResponse(status_code=202, content=_status_body(record))


@router.get("/runs/{run_id}")
async def get_run(run_id: str, runner: MarketResearchRunner = Depends(get_runner)):
    record = await runner.registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    return _status_body(record)


@router.get("/runs/{run_id}/output")
async def get_run_output(run_id: str, runner: MarketResearchRunner = Depends(get_runner)):
    record = await runner.registry.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    if record.status not in FINISHED:
        raise HTTPException(status_code=409, detail=f"Run {run_id} is {record.status}; poll {PREFIX}/runs/{run_id}")
    if record.status == "failed":
        raise HTTPException(status_code=409, detail=f"Run {run_id} failed: {record.error}")
    return _output_file(record)


@router.get("/latest")
async def get_latest(
    region: str = "US",
    max_age_minutes: int = Query(default=60, ge=1, le=7 * 24 * 60),
    runner: MarketResearchRunner = Depends(get_runner),
):
    since = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    record = await runner.registry.latest_success(region, since)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No finished {region} run in the last {max_age_minutes} minutes")
    return _output_file(record)


@router.get("/schema")
async def get_schema():
    return output_json_schema()


@router.get("/health")
async def health(runner: MarketResearchRunner = Depends(get_runner)):
    settings = runner.service.settings
    storage_ok = True
    try:
        await runner.registry.get("__healthcheck__")
    except Exception:
        storage_ok = False
    return {
        "status": "ok" if storage_ok and settings.fred_api_key else "degraded",
        "keys": {
            "fred": bool(settings.fred_api_key),
            "tavily": bool(settings.tavily_api_key),
            "groq": bool(os.getenv("GROQ_API_KEY")),
        },
        "market_data_provider": settings.market_data_provider,
        "news_provider": settings.news_provider,
        "registry": type(runner.registry).__name__,
        "cache": type(runner.service.cache).__name__,
        "storage_reachable": storage_ok,
        "auth_required": bool(settings.api_token),
    }


@ui_router.get("/articles")
async def get_article(
    run_id: str = Query(description="The run that cited the article, e.g. mr_20261016T072553Z_4faf42"),
    url: str = Query(description="The article URL exactly as recorded in that run's news list"),
    runner: MarketResearchRunner = Depends(get_runner),
):
    """Reader view of one news article a run cited: the agent's summary and
    tags, plus the extracted article text when the site allows it
    (`status: "ok"`), otherwise `status: "unavailable"` with a reason."""
    try:
        return await read_article(runner.service.out_dir, run_id, url, runner.service.cache)
    except ArticleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
