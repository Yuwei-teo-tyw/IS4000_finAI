"""
Product Specialist Agent integration.

The Portfolio Manager reads the same product shelf as the Product
Recommender (app/agents/product_recommender/shelf.py), in-process, so the PS
screen and the Portfolio Manager work from one product list.
`fetch_product_candidates()` validates each product individually against
the PM's own ProductCandidate contract (one malformed product is dropped and
reported, not allowed to sink the whole shelf) and labels provenance.
"""
import logging
from typing import Any

from app.agents.portfolio_manager.schemas.upstream import ProductCandidate, ProductCandidates, UpstreamResult
from app.agents.product_recommender import shelf

logger = logging.getLogger(__name__)

# Provenance of the shared shelf: "MOCK" while it is illustrative data.
PRODUCT_CANDIDATES_SOURCE = shelf.SHELF_SOURCE


async def get_product_candidates(base_currency: str | None = None) -> dict[str, Any]:
    """Return the shared product shelf as raw JSON."""
    return shelf.load_raw()


async def fetch_product_candidates(base_currency: str | None = None) -> UpstreamResult:
    source = PRODUCT_CANDIDATES_SOURCE
    try:
        raw = await get_product_candidates(base_currency)
    except Exception as e:
        logger.warning("Product candidate retrieval failed: %s", type(e).__name__)
        return UpstreamResult(source=source, status="UNAVAILABLE", issues=["Product candidates could not be retrieved."])
    return shelf.validate(raw, ProductCandidate, ProductCandidates, source)
