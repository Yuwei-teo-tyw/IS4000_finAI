"""
Product Specialist Agent integration.

`get_product_candidates()` is the single integration point: today it
returns illustrative mock JSON; later it should call the Product
Specialist Agent's API. `fetch_product_candidates()` validates each
product individually (one malformed product is dropped and reported, not
allowed to sink the whole shelf) and labels provenance.
"""
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.portfolio_manager.schemas.upstream import ProductCandidate, ProductCandidates, UpstreamResult

logger = logging.getLogger(__name__)

_MOCK_PATH = Path(__file__).parent / "mock_data" / "product_candidates.json"

# Set to "LIVE" once get_product_candidates() calls the real agent.
PRODUCT_CANDIDATES_SOURCE = "MOCK"


async def get_product_candidates(base_currency: str | None = None) -> dict[str, Any]:
    """Return the Product Specialist Agent's candidate products as raw JSON."""
    # INPUT API HERE: Replace mock product data with the Product Specialist Agent API response.
    # e.g.
    #   async with httpx.AsyncClient(timeout=10) as client:
    #       resp = await client.get(f"{os.environ['PRODUCT_SPECIALIST_API_URL']}/products",
    #                               params={"base_currency": base_currency})
    #       resp.raise_for_status()
    #       return resp.json()
    # ...and set PRODUCT_CANDIDATES_SOURCE = "LIVE".
    with open(_MOCK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def fetch_product_candidates(base_currency: str | None = None) -> UpstreamResult:
    source = PRODUCT_CANDIDATES_SOURCE
    try:
        raw = await get_product_candidates(base_currency)
    except Exception as e:
        logger.warning("Product candidate retrieval failed: %s", type(e).__name__)
        return UpstreamResult(source=source, status="UNAVAILABLE", issues=["Product candidates could not be retrieved."])

    if not isinstance(raw, dict) or not isinstance(raw.get("products"), list):
        return UpstreamResult(
            source=source, status="UNAVAILABLE", issues=["Product response has no 'products' list."]
        )

    issues: list[str] = []
    valid: list[ProductCandidate] = []
    for i, item in enumerate(raw["products"]):
        try:
            valid.append(ProductCandidate.model_validate(item))
        except ValidationError as e:
            pid = item.get("product_id", f"index {i}") if isinstance(item, dict) else f"index {i}"
            issues.append(f"Product {pid} dropped: failed schema validation ({e.error_count()} errors).")

    try:
        shelf = ProductCandidates.model_validate({**raw, "products": []})
    except ValidationError as e:
        return UpstreamResult(
            source=source, status="UNAVAILABLE",
            issues=[f"Product response envelope failed validation ({e.error_count()} errors)."],
        )
    shelf.products = valid

    if not valid:
        issues.append("No valid product candidates were returned.")
        return UpstreamResult(source=source, status="UNAVAILABLE", data=shelf, issues=issues)

    partial = [p.product_id for p in valid if p.data_completeness != "COMPLETE"]
    if partial:
        issues.append(f"Products with incomplete data: {', '.join(partial)}.")
    status = "INCOMPLETE" if (partial or len(valid) < len(raw["products"])) else "OK"
    return UpstreamResult(source=source, status=status, data=shelf, issues=issues)
