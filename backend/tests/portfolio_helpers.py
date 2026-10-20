"""
Shared helpers for the Portfolio Manager tests. Nothing here touches the
network: the LLM is disabled (or replaced by conftest.FakeLLM), upstream
fetchers can be swapped for stubs, and the clock is fixed so data-staleness
checks are deterministic.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.portfolio_manager.config import Settings
from app.agents.portfolio_manager.explain.llm_client import LLMUnavailable
from app.agents.portfolio_manager.schemas.upstream import UpstreamResult
from app.agents.portfolio_manager.service import PortfolioService
from app.agents.portfolio_manager.upstream import market_analysis, product_specialist
from app.agents.product_recommender import shelf
from app.endpoints.portfolio_manager import install_validation_handler, router

SAMPLE_REQUEST = (Path(__file__).resolve().parent.parent / "app" / "agents" / "portfolio_manager"
                  / "samples" / "sample_request.json")
BASE = "/agents/portfolio-manager"
GENERATE = f"{BASE}/portfolio/generate"
FIXED_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def settings(**overrides) -> Settings:
    base = dict(llm_enabled=True, llm_model="test-model", llm_timeout_seconds=5, llm_max_tokens=100,
                store_max_items=100, market_stale_after_days=30, product_stale_after_days=90)
    base.update(overrides)
    return Settings(**base)


def no_llm(_settings):
    raise LLMUnavailable("disabled in tests.")


def make_service(llm_factory=no_llm, **kw) -> PortfolioService:
    return PortfolioService(settings=kw.pop("settings", settings()), llm_factory=llm_factory,
                            clock=lambda: FIXED_NOW, **kw)


def make_client(service=None) -> TestClient:
    """Minimal app with only the Portfolio Manager router - no Postgres, no network, no LLM."""
    app = FastAPI()
    app.include_router(router)
    install_validation_handler(app)
    app.state.portfolio_manager = service or make_service()
    return TestClient(app)


def sample_request() -> dict:
    return json.loads(SAMPLE_REQUEST.read_text(encoding="utf-8"))


def request_with(request_id="PM-TEST", remove=(), **profile_overrides) -> dict:
    req = sample_request()
    req["request_id"] = request_id
    req["client_profile"].update(copy.deepcopy(profile_overrides))
    for f in remove:
        req["client_profile"].pop(f, None)
    return req


def mock_market() -> dict:
    return json.loads(market_analysis._MOCK_PATH.read_text(encoding="utf-8"))


def mock_products() -> dict:
    return json.loads(shelf.SHELF_PATH.read_text(encoding="utf-8"))


def market_fetcher_from(raw_or_exc):
    """Build a fetch_market_analysis replacement that runs the real
    validation over a custom raw payload (or raises)."""
    async def fetch(base_currency=None) -> UpstreamResult:
        async def get(_=None):
            if isinstance(raw_or_exc, BaseException):
                raise raw_or_exc
            return raw_or_exc
        original = market_analysis.get_market_analysis
        market_analysis.get_market_analysis = get
        try:
            return await market_analysis.fetch_market_analysis(base_currency)
        finally:
            market_analysis.get_market_analysis = original
    return fetch


def product_fetcher_from(raw_or_exc):
    async def fetch(base_currency=None) -> UpstreamResult:
        async def get(_=None):
            if isinstance(raw_or_exc, BaseException):
                raise raw_or_exc
            return raw_or_exc
        original = product_specialist.get_product_candidates
        product_specialist.get_product_candidates = get
        try:
            return await product_specialist.fetch_product_candidates(base_currency)
        finally:
            product_specialist.get_product_candidates = original
    return fetch


def offered(resp: dict) -> list[dict]:
    return [o for o in resp["portfolio_options"]
            if o["suitability_status"] in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS")]


def option(resp: dict, option_id: str) -> dict:
    return next(o for o in resp["portfolio_options"] if o["option_id"] == option_id)


def assert_reconciles(opt: dict) -> None:
    value = opt["eligible_portfolio_value"]
    sels = opt["product_selections"]
    assert abs(sum(s["allocation_percentage"] for s in sels) - 100) < 0.011
    assert abs(sum(s["investment_amount"] for s in sels) - value) < 0.01 * (len(sels) + 1)
    assert abs(sum(a["allocation_percentage"] for a in opt["asset_allocation"]) - 100) < 0.011
    for s in sels:
        assert abs(value * s["allocation_percentage"] / 100 - s["investment_amount"]) < 0.01 * (len(sels) + 1)
    for c in opt["constraint_checks"]:
        assert c["status"] != "FAIL", c
