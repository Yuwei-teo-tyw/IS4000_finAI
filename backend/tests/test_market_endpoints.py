"""
HTTP contract for the market researcher (how the main agent drives it):
FastAPI TestClient on a minimal app with only the market router, an
in-memory run registry, and the stubbed service from test_market_service -
no Postgres, no network, no LLM.
"""
import asyncio
import dataclasses
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.agents.market_researcher.news_tagging as tagging_module
from app.agents.market_researcher.news_tagging import NewsTagBatch
from app.agents.market_researcher.runs import InMemoryRunRegistry, MarketResearchRunner
from app.agents.market_researcher.schemas import MarketResearchOutput, output_json_schema
from app.endpoints.market_researcher import router

from conftest import FakeLLM
from test_market_service import make_service

BASE = "/agents/market-researcher"


@pytest.fixture(autouse=True)
def fake_tagger(monkeypatch):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(NewsTagBatch(items=[])))
    monkeypatch.delenv("MARKET_RESEARCH_API_TOKEN", raising=False)


def build_client(tmp_path, service=None, **runner_kw):
    service = service or make_service(tmp_path)
    service.settings = dataclasses.replace(service.settings, fred_api_key=service.settings.fred_api_key or "test-key")
    app = FastAPI()
    app.include_router(router)
    app.state.market_research = MarketResearchRunner(InMemoryRunRegistry(), service, **runner_kw)
    return TestClient(app)


def poll(client, run_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"{BASE}/runs/{run_id}").json()
        if body["status"] in ("succeeded", "partial", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def test_async_run_lifecycle(tmp_path):
    with build_client(tmp_path) as client:
        resp = client.post(f"{BASE}/runs", json={"focus": ["rates"]})
        assert resp.status_code == 202
        created = resp.json()
        assert created["status"] in ("queued", "running")
        assert created["status_url"] == f"{BASE}/runs/{created['run_id']}"
        assert "json_path" not in created                      # server paths aren't leaked

        status = poll(client, created["run_id"])
        assert status["status"] == "succeeded" and status["finished_at"]

        out = client.get(status["output_url"])
        assert out.status_code == 200 and out.headers["content-type"] == "application/json"
        output = MarketResearchOutput.model_validate(out.json())
        assert output.run_id == created["run_id"] and output.request.focus == ["rates"]


def test_wait_true_returns_output(tmp_path):
    with build_client(tmp_path) as client:
        resp = client.post(f"{BASE}/runs?wait=true", json={})
        assert resp.status_code == 200
        assert MarketResearchOutput.model_validate(resp.json()).indicators


def test_latest_and_schema(tmp_path):
    with build_client(tmp_path) as client:
        assert client.get(f"{BASE}/latest").status_code == 404
        run_id = client.post(f"{BASE}/runs?wait=true", json={}).json()["run_id"]
        latest = client.get(f"{BASE}/latest", params={"region": "US", "max_age_minutes": 5})
        assert latest.status_code == 200 and latest.json()["run_id"] == run_id
        assert client.get(f"{BASE}/latest", params={"region": "EU"}).status_code == 404
        assert client.get(f"{BASE}/schema").json() == output_json_schema()


def test_validation_and_unsupported_region(tmp_path):
    with build_client(tmp_path) as client:
        assert client.post(f"{BASE}/runs", json={"lookback_days_news": 99}).status_code == 422
        assert client.post(f"{BASE}/runs", json={"region": "MARS"}).status_code == 422
        resp = client.post(f"{BASE}/runs", json={"region": "EU"})
        assert resp.status_code == 422 and "not supported" in resp.json()["detail"]


def test_unknown_run_and_output_not_ready(tmp_path):
    class SlowService:
        def __init__(self, inner):
            self.inner, self.settings, self.cache = inner, inner.settings, inner.cache

        async def run(self, request, run_id=None):
            await asyncio.sleep(0.5)
            return await self.inner.run(request, run_id=run_id)

    with build_client(tmp_path, service=SlowService(make_service(tmp_path))) as client:
        assert client.get(f"{BASE}/runs/nope").status_code == 404
        assert client.get(f"{BASE}/runs/nope/output").status_code == 404
        run_id = client.post(f"{BASE}/runs", json={}).json()["run_id"]
        assert client.get(f"{BASE}/runs/{run_id}/output").status_code == 409
        # identical request while in flight is coalesced onto the same run
        assert client.post(f"{BASE}/runs", json={}).json()["run_id"] == run_id
        poll(client, run_id)


def test_queue_full_returns_429(tmp_path):
    class BlockingService:
        def __init__(self, inner):
            self.settings, self.cache = inner.settings, inner.cache

        async def run(self, request, run_id=None):
            await asyncio.sleep(30)

    with build_client(tmp_path, service=BlockingService(make_service(tmp_path)), max_concurrent=1, max_queued=0) as client:
        assert client.post(f"{BASE}/runs", json={"focus": ["a"]}).status_code == 202
        resp = client.post(f"{BASE}/runs", json={"focus": ["b"]})
        assert resp.status_code == 429 and resp.headers["retry-after"] == "30"
        client.app.state.market_research._tasks.clear()


def test_failed_run_reports_error(tmp_path):
    class BrokenService:
        def __init__(self, inner):
            self.settings, self.cache = inner.settings, inner.cache

        async def run(self, request, run_id=None):
            raise RuntimeError("disk full")

    with build_client(tmp_path, service=BrokenService(make_service(tmp_path))) as client:
        resp = client.post(f"{BASE}/runs?wait=true", json={})
        assert resp.status_code == 502
        assert resp.json()["status"] == "failed" and "disk full" in resp.json()["error"]
        assert client.get(f"{BASE}/runs/{resp.json()['run_id']}/output").status_code == 409


def test_missing_fred_key_returns_503(tmp_path):
    service = make_service(tmp_path)
    with build_client(tmp_path, service=service) as client:
        service.settings = dataclasses.replace(service.settings, fred_api_key=None)
        assert client.post(f"{BASE}/runs", json={}).status_code == 503


def test_bearer_token_enforced_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_RESEARCH_API_TOKEN", "s3cret")
    with build_client(tmp_path) as client:
        assert client.get(f"{BASE}/schema").status_code == 401
        assert client.get(f"{BASE}/schema", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(f"{BASE}/schema", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_health(tmp_path):
    with build_client(tmp_path) as client:
        body = client.get(f"{BASE}/health").json()
        assert body["keys"]["fred"] is True and body["registry"] == "InMemoryRunRegistry"
        assert body["storage_reachable"] is True
