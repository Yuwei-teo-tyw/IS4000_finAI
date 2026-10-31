"""
Chat entry for product recommendations (PM asks Geneva; the PS role is gone).

Runs the same ProductRecommenderService.recommend_explained as POST /agents/product-recommender/recommend and
returns the same RecommendResponse, so the frontend renders one structure either way. The client profile is built
only from stored data (client record, saved IPS, holdings); nothing is guessed - missing fields stay None and the
service reports them under `missing_information`. Proposal-only.
"""
import re
from typing import Any, Optional

from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.product_recommender.schemas import RecommendRequest, RecommendResponse
from app.agents.product_recommender.service import ProductRecommenderService

_REQUEST_RE = re.compile(
    r"\b(recommend\w*|shortlist\w*|product\s+(?:ideas?|suggestions?|shelf|picks?)|which\s+products?|"
    r"suggest\w*\s+(?:some\s+|any\s+)?(?:products?|funds?|etfs?|bonds?|instruments?)|"
    r"(?:products?|funds?|etfs?)\s+(?:for|to\s+buy|to\s+consider))\b", re.I)
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\+|-|to|–)?\s*(?:\d+\s*)?(?:years?|yrs?)", re.I)


_CAPACITY_BY_LEVEL = {1: "Low", 2: "Moderately low", 3: "Moderate", 4: "Moderately high", 5: "High"}


def is_product_request(message: str) -> bool:
    return bool(message and _REQUEST_RE.search(message))


def wants_product_recommendation(context: Any, message: str) -> bool:
    """PM role + a client in focus + a product-recommendation ask. Anything else goes to the normal graph."""
    if not isinstance(context, dict) or str(context.get("role", "")).lower() != "pm":
        return False
    cid = context.get("client_id")
    return isinstance(cid, str) and bool(cid.strip()) and is_product_request(message)


def build_client_profile(client_id: str, store=None, portfolio: Optional[dict] = None) -> dict:
    """ClientProfile dict from the client record, latest IPS and (if given) the portfolio payload."""
    if store is None:
        from app.agents.client_profiling.store import get_default_store
        store = get_default_store()
    client = store.get_client(client_id)
    if client is None:
        raise LookupError(f"Unknown client {client_id}")
    p: dict = {"client_id": client_id, "base_currency": "SGD"}
    if client.aum_sgd:
        p["total_aum"] = p["investable_assets"] = float(client.aum_sgd)
    if client.risk_category:
        p["risk_appetite"] = client.risk_category
    if isinstance(client.risk_cap, int) and 1 <= client.risk_cap <= 5:
        p["risk_tolerance_score"] = client.risk_cap
        # risk_cap is the client's recorded risk ceiling (1-5); it is the only stored capacity signal, so it is used as
        # the capacity level. Drawdown, income, expenses etc. are not stored and stay missing (reported, not guessed).
        p["risk_capacity"] = _CAPACITY_BY_LEVEL[client.risk_cap]
    ips, _ = store.latest_ips(client_id)
    if ips is not None:
        from app.agents.client_profiling.ips_model import normalize_data
        data = normalize_data(ips.data, ips.issued_on)
        period = (data.get("philosophy") or {}).get("investmentPeriod") or ""
        m = _YEARS_RE.search(str(period))
        if m and 0 < float(m.group(1)) <= 100:
            p["financial_goals"] = [{"goal": "IPS investment horizon", "years_to_goal": float(m.group(1)), "priority": "High"}]
    rows = [h for h in (portfolio or {}).get("holdings", []) if h.get("market_value")]
    if rows:
        p["current_holdings"] = [{"product_name": h.get("name") or h.get("ticker"), "asset_class": h.get("asset_class"),
                                  "market_value": h["market_value"]} for h in rows]
    return p


def _portfolio(client_id: str) -> Optional[dict]:
    try:
        from app.agents.client_portfolio import service
        res = service.get_client_portfolio(client_id)
        return res if res.get("available") else None
    except Exception:
        return None  # portfolio DB down: holdings simply absent, never invented


async def recommend_for_chat(client_id: str, service: ProductRecommenderService, store=None,
                             portfolio: Optional[dict] = None) -> RecommendResponse:
    profile = build_client_profile(client_id, store, portfolio if portfolio is not None else _portfolio(client_id))
    req = RecommendRequest(client_id=client_id, client_profile=ClientProfile.model_validate(profile))
    return await service.recommend_explained(req)
