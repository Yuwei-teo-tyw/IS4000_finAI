import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.agents.client_profiling.store import StoreUnavailableError, get_default_store
from app.agents.product_recommender.service import ProductRecommenderService
from app.reports.pack_generator import RM_CONTEXT_MAX, PackGenerationError, generate_review_pack
from app.reports.render import render_review_pack, template_version

router = APIRouter(prefix="/review-pack", tags=["review-pack"])


class DocMeta(BaseModel):
    title: str = Field(max_length=200)
    client_name: str = Field(max_length=200)
    version: str = Field(max_length=100)
    date: str = Field(max_length=50)


class Section(BaseModel):
    n: int
    title: str = Field(max_length=200)
    owner_label: str = Field(max_length=100)
    complete: bool
    text: str = Field(default="", max_length=20_000)
    wide: bool = False
    chart: str | None = None  # placeholder name, resolved by the chart registry
    kind: str | None = None  # "signoff" renders signature slots


class AllocationRow(BaseModel):
    asset_class: str
    saa: float
    old_taa: float
    new_taa: float
    band: float


class Signature(BaseModel):
    data_url: str = Field(max_length=2_500_000)
    signed_at: str = Field(max_length=100)


class RenderRequest(BaseModel):
    doc: DocMeta
    sections: list[Section]
    allocation: list[AllocationRow]
    signatures: dict[str, Signature] = {}


@router.post("/render", response_class=HTMLResponse)
async def render(req: RenderRequest):
    """Render the pack with the RM's current section text. Returns standalone HTML."""
    try:
        html = render_review_pack(req.model_dump())
    except KeyError as e:  # unknown chart placeholder
        raise HTTPException(status_code=422, detail=str(e))
    return HTMLResponse(html, headers={"X-Template-Version": template_version()})


def get_service(request: Request) -> ProductRecommenderService:
    service = getattr(request.app.state, "product_recommender", None)
    if service is None:
        service = ProductRecommenderService()
        request.app.state.product_recommender = service
    return service


class GenerateRequest(BaseModel):
    client_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    rm_context: Optional[str] = Field(default=None, max_length=RM_CONTEXT_MAX)


async def _fresh_market(request: Request, purpose: str) -> None:
    """Make sure the Market Analysis Agent has a run from the last 24h (reused, or started and awaited) before the pack
    reads market data. A failure is not fatal: the pack then reports the market as unavailable."""
    from app.agents.market_researcher.ips_context import ensure_market_run
    await ensure_market_run(getattr(request.app.state, "market_research", None), purpose=purpose)


@router.post("/generate")
async def generate(req: GenerateRequest, request: Request, service: ProductRecommenderService = Depends(get_service)):
    """The RM's Review Pack, sections A-G. Requires an Active IPS (409 otherwise). It never proposes a new TAA or
    holding shifts: D and F show the previous approved review's, or say there is none (the PM proposes new ones)."""
    await _fresh_market(request, "Review pack generation")
    try:
        return await generate_review_pack(req.client_id, req.rm_context, service=service, stage="rm")
    except PackGenerationError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


class PmProposalsRequest(BaseModel):
    client_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


@router.post("/pm-proposals")
async def pm_proposals(req: PmProposalsRequest, request: Request, service: ProductRecommenderService = Depends(get_service)):
    """When the PM opens a pack sent to them: the new TAA (from the IPS SAA, the CIO house view and the Market Analysis
    Agent's run) and holding shifts (from the Client Portfolio Agent's holdings and the Product Specialist's shortlist).
    Proposals only; the PM edits and approves them in the pack."""
    await _fresh_market(request, "Review pack PM proposals")
    try:
        full = await generate_review_pack(req.client_id, None, service=service, stage="pm")
    except PackGenerationError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    by = {s["id"]: s for s in full["sections"]}
    return {"client_id": req.client_id, "taa": full["taa"], "taa_stage": "pm", "holdings_shifts": full["holdings_shifts"],
            "sections": [by["D"], by["F"]], "sources": full["sources"], "generated_at": full["generated_at"]}


# --- Review Pack state: shared server-side copy for RM and PM (whole document, last write wins) ---
REVIEW_STATE_MAX_BYTES = 2_000_000
CLIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


def _reject_constant(name: str):
    raise ValueError(f"non-standard JSON constant {name}")


def _unavailable(e: StoreUnavailableError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(e))


@router.get("/states")
async def list_review_pack_states():
    """All clients' Review Pack states (used by the PM inbox)."""
    try:
        return {"states": get_default_store().list_review_pack_states()}
    except StoreUnavailableError as e:
        raise _unavailable(e)


@router.get("/state/{client_id}")
async def get_review_pack_state(client_id: str = Path(pattern=CLIENT_ID_PATTERN)):
    try:
        state = get_default_store().get_review_pack_state(client_id)
    except StoreUnavailableError as e:
        raise _unavailable(e)
    if state is None:
        raise HTTPException(status_code=404, detail="No review pack state.")
    return {"state": state}


@router.put("/state/{client_id}")
async def put_review_pack_state(request: Request, client_id: str = Path(pattern=CLIENT_ID_PATTERN)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > REVIEW_STATE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Review pack state too large.")
    raw = await request.body()
    if len(raw) > REVIEW_STATE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Review pack state too large.")
    try:
        body = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Body must be JSON.")
    if not isinstance(body, dict) or not isinstance(body.get("state"), dict):
        raise HTTPException(status_code=422, detail="Body must be {\"state\": <object>}.")
    state = body["state"]
    try:
        updated_at = get_default_store().put_review_pack_state(client_id, state)
    except StoreUnavailableError as e:
        raise _unavailable(e)
    return {"state": state, "updated_at": updated_at}


@router.delete("/state/{client_id}")
async def delete_review_pack_state(client_id: str = Path(pattern=CLIENT_ID_PATTERN)):
    try:
        return {"deleted": get_default_store().delete_review_pack_state(client_id)}
    except StoreUnavailableError as e:
        raise _unavailable(e)
