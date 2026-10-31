"""RM send -> PM edits 3L/SAA -> PM returns -> RM activates. Json store and an isolated Postgres schema."""
import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling import embeddings
from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints import client_profiling as ep
from app.endpoints import ips_handover

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
U = "/agents/client-profiling"
app = FastAPI()
app.include_router(ep.router)
app.include_router(ips_handover.router)


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(params=["json", pytest.param("pg", marks=pytest.mark.skipif(not _reachable(), reason="Postgres not reachable"))])
def api(request, monkeypatch):
    def vec(t):
        v = [0.0] * 768
        for i, ch in enumerate(t.lower()):
            v[(ord(ch) + i) % 768] += 1.0
        return v
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [vec(t) for t in texts])
    if request.param == "json":
        s = DocumentStore()
        monkeypatch.setattr(store_mod, "_default", s)
        yield TestClient(app)
        return
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(store_mod, "_default", PostgresStore(schema=name))
    yield TestClient(app)
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


DATA = {
    "goals": [{"key": "returnRequirements", "title": "Return Requirements", "bullets": ["Keep capital safe"]}],
    "threeLProportion": {"liquidity": {"pct": 10, "reason": "near-term"}, "longevity": {"pct": 80, "reason": "lifestyle"},
                         "legacy": {"pct": 10, "reason": "estate"}},
    "threeL": [{"portfolio": "Liquidity", "strategy": None, "reason": "cash"},
               {"portfolio": "Longevity", "strategy": "C", "strategyName": "Yield", "reason": "moderate"},
               {"portfolio": "Legacy", "strategy": "B", "strategyName": "Income", "reason": "long"}],
}


@pytest.fixture
def sent(api):
    r = api.post(f"{U}/ips/jft", json={"data": DATA, "status": "Draft"})
    assert r.status_code == 200, r.text
    v = r.json()["ips"]["version"]
    assert api.post(f"{U}/ips-send/jft", json={"version": v}).status_code == 200
    return api, v


def test_pm_starts_from_rm_send(sent):
    api, v = sent
    w = api.get(f"{U}/pm-ips/jft").json()
    assert w["status"] == "Sent to PM" and not w["edited"]
    assert {b: w["threeL"][b]["pct"] for b in w["threeL"]} == {"liquidity": 10, "longevity": 80, "legacy": 10}
    assert w["saa"]["longevity"]["strategy"] == "C" and w["saa"]["longevity"]["optionId"] == "C"
    assert w["saa"]["legacy"]["strategy"] == "B"
    assert "liquidity" not in w["saa"]
    snap = api.get(f"{U}/ips-send/jft/snapshot").json()
    assert snap["data"]["threeL"][1]["strategy"] == "C"


def test_pm_edit_persists_and_validates(sent):
    api, v = sent
    r = api.put(f"{U}/pm-ips/jft", json={"threeL": {"liquidity": {"pct": 20}, "longevity": {"pct": 70}, "legacy": {"pct": 10}},
                                         "saa": {"longevity": {"strategy": "D"}}})
    assert r.status_code == 200, r.text
    w = api.get(f"{U}/pm-ips/jft").json()
    assert w["edited"] and w["threeL"]["liquidity"]["pct"] == 20 and w["saa"]["longevity"]["strategy"] == "D"
    assert w["saa"]["longevity"]["source"] == "pm" and w["saa"]["legacy"]["source"] == "rm"
    assert api.get(f"{U}/ips-allocation/overrides/jft").json()["overrides"][0]["to"] == "D"
    bad = lambda body: api.put(f"{U}/pm-ips/jft", json=body).status_code
    assert bad({"threeL": {"liquidity": {"pct": 50}}}) == 422           # does not add up to 100
    assert bad({"saa": {"liquidity": {"strategy": "A"}}}) == 422        # Liquidity has no SAA
    assert bad({"saa": {"legacy": {"strategy": "Z"}}}) == 422           # unknown strategy
    assert bad({"saa": {"legacy": {"strategy": "A", "weights": {"Bonds": 50}}}}) == 422
    assert api.get(f"{U}/pm-ips/jft").json()["threeL"]["liquidity"]["pct"] == 20  # rejected edits changed nothing


def test_return_writes_into_ips_and_activate(sent):
    api, v = sent
    assert api.post(f"{U}/ips/jft/{v}/activate").status_code == 409     # not returned yet
    api.put(f"{U}/pm-ips/jft", json={"threeL": {"liquidity": {"pct": 20}, "longevity": {"pct": 70}, "legacy": {"pct": 10}},
                                     "saa": {"legacy": {"strategy": "E"}}})
    r = api.post(f"{U}/pm-ips/jft/return")
    assert r.status_code == 200 and r.json()["status"] == "Returned by PM"
    assert api.get(f"{U}/ips-send/jft").json()["status"] == "Returned by PM"
    assert api.get(f"{U}/ips-send/jft").json()["outdated"] is False
    ips = api.get(f"{U}/ips/jft").json()["versions"][0]
    d = ips["data"]
    assert {k: d["threeLProportion"][k]["pct"] for k in ("liquidity", "longevity", "legacy")} == {"liquidity": 20, "longevity": 70, "legacy": 10}
    by = {b["portfolio"]: b for b in d["threeL"]}
    assert by["Legacy"]["strategy"] == "E" and by["Longevity"]["strategy"] == "C" and by["Liquidity"]["strategy"] is None
    assert d["goals"][0]["bullets"] == ["Keep capital safe"]            # RM's other sections kept
    part4 = next(p for p in ips["parts"] if p["part"] == 4)
    assert "Legacy: Strategy E" in part4["body"] and "Liquidity:" not in part4["body"]
    assert api.put(f"{U}/pm-ips/jft", json={"saa": {"legacy": {"strategy": "A"}}}).status_code == 409  # locked after return
    a = api.post(f"{U}/ips/jft/{v}/activate")
    assert a.status_code == 200 and a.json()["clientStatus"] == "Monitoring Phase"
    idx = a.json()["indexing"]
    assert idx["status"] in ("indexed", "pending")  # pending on the json store (no vector DB)
    if idx["status"] == "indexed":
        assert idx["chunks"] > 0
    got = api.get(f"{U}/ips/jft").json()
    assert got["current_version"] == v and got["versions"][0]["status"] == "Active"


def test_return_needs_send_and_activate_supersedes(api):
    assert api.post(f"{U}/pm-ips/jft/return").status_code == 404
    old = api.post(f"{U}/ips/jft", json={"data": DATA, "status": "Active"}).json()["ips"]["version"]
    new = api.post(f"{U}/ips/jft", json={"data": DATA, "status": "Draft"}).json()["ips"]["version"]
    api.post(f"{U}/ips-send/jft", json={"version": new})
    assert api.post(f"{U}/pm-ips/jft/return").status_code == 200
    assert api.post(f"{U}/ips/jft/{old}/activate").status_code == 409   # only the returned version
    assert api.post(f"{U}/ips/jft/{new}/activate").json()["superseded"] == [old]
