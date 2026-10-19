from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

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
