"""
The single product shelf, shared by the Product Recommender and the
Portfolio Agent.

`load_raw()` is the integration point. It reads data/shelf_live.json (real
funds, built from the Advised Portfolios Performance workbook by
build_live_shelf.py) when present, else the illustrative data/shelf.json.
PRODUCT_SHELF=mock forces the illustrative shelf; the test suite sets it.
`validate()` checks each product on its own, so one malformed product is
dropped and reported instead of sinking the whole shelf, and labels provenance.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.portfolio_agent.schemas.upstream import UpstreamResult
from app.agents.product_recommender.schemas import Shelf, ShelfProduct

logger = logging.getLogger(__name__)

MOCK_SHELF_PATH = Path(__file__).parent / "data" / "shelf.json"
LIVE_SHELF_PATH = Path(__file__).parent / "data" / "shelf_live.json"

_use_live = os.getenv("PRODUCT_SHELF", "live").strip().lower() != "mock" and LIVE_SHELF_PATH.exists()
SHELF_PATH = LIVE_SHELF_PATH if _use_live else MOCK_SHELF_PATH

# This label, not the payload's own claims, decides how the data is reported.
SHELF_SOURCE = "LIVE" if _use_live else "MOCK"


def load_raw() -> dict[str, Any]:
    with open(SHELF_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate(raw: Any, item_model: type[BaseModel], envelope_model: type[BaseModel], source: str) -> UpstreamResult:
    """Validate a shelf payload product by product. Never raises."""
    if not isinstance(raw, dict) or not isinstance(raw.get("products"), list):
        return UpstreamResult(source=source, status="UNAVAILABLE", issues=["Product response has no 'products' list."])

    issues: list[str] = []
    valid = []
    for i, item in enumerate(raw["products"]):
        try:
            valid.append(item_model.model_validate(item))
        except ValidationError as e:
            pid = item.get("product_id", f"index {i}") if isinstance(item, dict) else f"index {i}"
            issues.append(f"Product {pid} dropped: failed schema validation ({e.error_count()} errors).")

    try:
        envelope = envelope_model.model_validate({**raw, "products": []})
    except ValidationError as e:
        return UpstreamResult(
            source=source, status="UNAVAILABLE",
            issues=[f"Product response envelope failed validation ({e.error_count()} errors)."],
        )
    envelope.products = valid

    if not valid:
        issues.append("No valid product candidates were returned.")
        return UpstreamResult(source=source, status="UNAVAILABLE", data=envelope, issues=issues)

    partial = [p.product_id for p in valid if p.data_completeness != "COMPLETE"]
    if partial:
        issues.append(f"Products with incomplete data: {', '.join(partial)}.")
    status = "INCOMPLETE" if (partial or len(valid) < len(raw["products"])) else "OK"
    return UpstreamResult(source=source, status=status, data=envelope, issues=issues)


def load_shelf() -> UpstreamResult:
    """The shelf as ShelfProducts (with the PS presentation fields)."""
    try:
        raw = load_raw()
    except Exception as e:  # IO / JSON errors
        logger.warning("Product shelf could not be read: %s", type(e).__name__)
        return UpstreamResult(source=SHELF_SOURCE, status="UNAVAILABLE", issues=["Product shelf could not be read."])
    return validate(raw, ShelfProduct, Shelf, SHELF_SOURCE)
