"""GET /ips/{client_id}: frontend-shaped IPS versions, newest first, per-client, read-only."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DocumentStore
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling/ips"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_STORE", "json")
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    return TestClient(app)


def test_ser_two_versions_newest_first(client):
    j = client.get(f"{U}/ser").json()
    assert j["client_id"] == "ser" and j["current_version"] == 2
    assert [(v["version"], v["status"]) for v in j["versions"]] == [(2, "Active"), (1, "Superseded")]
    v = j["versions"][0]
    assert set(v) == {"version", "issuedOn", "status", "author", "summary", "parts", "data"}
    assert [p["part"] for p in v["parts"]] == [1, 2, 3, 4, 5, 6]
    assert set(v["parts"][0]) == {"part", "title", "owner", "status", "body"}


@pytest.mark.parametrize("cid,cur,status", [("dso", 1, "Active"), ("teo", 1, "Active"), ("jfr", None, "Draft"), ("sha", None, "Draft")])
def test_other_clients(client, cid, cur, status):
    j = client.get(f"{U}/{cid}").json()
    assert j["current_version"] == cur and [v["status"] for v in j["versions"]] == [status]


def test_unknown_client_404(client):
    assert client.get(f"{U}/nobody").status_code == 404
