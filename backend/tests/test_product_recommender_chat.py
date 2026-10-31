"""PM product recommendations via Geneva chat: same RecommendResponse as the REST route. Offline, no network."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_product_recommender import service

from app.agents.client_profiling.store import DocumentStore
from app.agents.product_recommender.chat import (build_client_profile, is_product_request, recommend_for_chat,
                                                 wants_product_recommendation)
from app.agents.product_recommender.schemas import RecommendResponse
from app.endpoints import router


def test_intent_and_gating():
    assert is_product_request("Can you recommend some products for this client?")
    assert not is_product_request("What is the CPI outlook?")
    ctx = {"role": "pm", "client_id": "ser"}
    assert wants_product_recommendation(ctx, "recommend products")
    assert not wants_product_recommendation({"role": "rm", "client_id": "ser"}, "recommend products")
    assert not wants_product_recommendation({"role": "pm"}, "recommend products")
    assert not wants_product_recommendation(None, "recommend products")


def test_profile_from_stored_data_and_same_response_as_rest():
    store = DocumentStore()
    prof = build_client_profile("ser", store)
    assert prof["risk_appetite"] == "Balanced" and prof["risk_tolerance_score"] == 3
    svc = service()
    resp = asyncio.run(recommend_for_chat("ser", svc, store=store, portfolio={}))
    assert isinstance(resp, RecommendResponse) and resp.client_id == "ser"
    assert resp.shortlist


def test_unknown_client_raises():
    with pytest.raises(LookupError):
        build_client_profile("nobody-here", DocumentStore())


def test_websocket_pm_request_returns_recommend_response(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.product_recommender = service()
    app.state.agent_graph = None  # must not be reached
    import app.agents.product_recommender.chat as chat
    monkeypatch.setattr(chat, "_portfolio", lambda cid: None)
    import app.endpoints as ep
    monkeypatch.setattr(ep.db, "touch_session", _noop)
    with TestClient(app) as c, c.websocket_connect("/agents/langgraph?greet=false") as ws:
        ws.send_json({"message": "recommend products", "context": {"role": "pm", "client_id": "ser"}})
        out = ws.receive_json()
    assert out["agent_name"] == "Product Recommender"
    RecommendResponse.model_validate(out["product_recommendation"])


async def _noop(*a, **k):
    return None
