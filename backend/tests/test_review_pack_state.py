"""Review Pack shared state endpoints (/review-pack/state*). Runs against the JSON/in-memory DocumentStore
and a real PostgresStore in a throwaway schema (skipped when Postgres is unreachable)."""
import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints import review_pack

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(params=["json", "pg"])
def client(request, monkeypatch):
    if request.param == "json":
        store = DocumentStore()
    else:
        if not _reachable():
            pytest.skip("Postgres not reachable")
        name = f"rp_test_{uuid.uuid4().hex[:10]}"
        store = PostgresStore(schema=name)
    monkeypatch.setattr(review_pack, "get_default_store", lambda: store)
    app = FastAPI()
    app.include_router(review_pack.router)
    yield TestClient(app)
    if request.param == "pg":
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


PACK = {"pack": {"title": "Review", "sections": [{"n": 1, "text": "A"}]}, "edits": {"1": "x"},
        "handover": {"status": "sent", "sentAt": "2026-10-30T10:00:00Z"}, "pmComments": []}


def test_put_get_list_delete_roundtrip(client):
    r = client.put("/review-pack/state/cli_1", json={"state": PACK})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == PACK and isinstance(body["updated_at"], str)

    assert client.get("/review-pack/state/cli_1").json() == {"state": PACK}
    assert client.get("/review-pack/states").json() == {"states": {"cli_1": PACK}}

    assert client.delete("/review-pack/state/cli_1").json() == {"deleted": True}
    assert client.delete("/review-pack/state/cli_1").json() == {"deleted": False}
    r = client.get("/review-pack/state/cli_1")
    assert r.status_code == 404 and r.json() == {"detail": "No review pack state."}
    assert client.get("/review-pack/states").json() == {"states": {}}


def test_last_write_wins(client):
    client.put("/review-pack/state/cli_2", json={"state": {"v": 1}})
    client.put("/review-pack/state/cli_2", json={"state": {"v": 2}})
    assert client.get("/review-pack/state/cli_2").json() == {"state": {"v": 2}}


@pytest.mark.parametrize("payload", [{"state": [1, 2]}, {"state": "text"}, {"state": None}, {"other": {}}, [1, 2]])
def test_non_object_state_rejected(client, payload):
    assert client.put("/review-pack/state/cli_3", json=payload).status_code == 422


def test_invalid_client_id_rejected(client):
    assert client.put("/review-pack/state/bad.id", json={"state": {}}).status_code == 422
    assert client.get("/review-pack/state/" + "a" * 65).status_code == 422
    assert client.delete("/review-pack/state/bad%20id").status_code == 422


def test_oversize_body_rejected(client):
    big = {"state": {"blob": "x" * 2_100_000}}
    assert client.put("/review-pack/state/cli_4", json=big).status_code == 413
