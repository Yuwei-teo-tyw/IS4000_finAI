"""
The CIO house view, one entry per asset class, curated from the monthly
House View report (see data/house_view.json for how each entry was read).

This is the one copy of the house view: the ranker, the PS chat and the
frontend's market views all read it, so they cannot disagree. The agent
reports it as written and never changes it.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.agents.portfolio_agent.taxonomy import ASSET_CLASS_ORDER
from app.agents.product_recommender.schemas import HouseView

logger = logging.getLogger(__name__)

HOUSE_VIEW_PATH = Path(__file__).parent / "data" / "house_view.json"
HOUSE_VIEW_SOURCE = "CURATED"


class HouseViewError(RuntimeError):
    """The house view file is missing, malformed, or does not cover every asset class."""


def load_house_view(path: Optional[Path] = None) -> HouseView:
    path = path or HOUSE_VIEW_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        hv = HouseView.model_validate(raw)
    except (OSError, ValueError, ValidationError) as e:
        logger.warning("House view could not be loaded: %s", type(e).__name__)
        raise HouseViewError("The house view could not be loaded.") from e

    expected = [ac.value for ac in ASSET_CLASS_ORDER]
    have = [v.asset_class for v in hv.views]
    missing = [ac for ac in expected if ac not in have]
    unknown = [ac for ac in have if ac not in expected]
    if missing or unknown or len(have) != len(set(have)):
        raise HouseViewError(
            f"The house view must have exactly one entry per asset class (missing: {missing}, unknown: {unknown})."
        )
    hv.views.sort(key=lambda v: expected.index(v.asset_class))
    return hv
