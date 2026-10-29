"""IS-101: send the draft IPS to the PM. Immutable snapshot, status, outdated flag, failure path, withdraw, isolation."""
import os
import re
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DocumentStore, StoreUnavailableError
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints import client_profiling as ep

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
U = "/agents/client-profiling"
app = FastAPI()
app.include_router(ep.router)


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(params=["json", pytest.param("pg", marks=pytest.mark.skipif(not _reachable(), reason="Postgres not reachable"))])
def st(request, monkeypatch):
    if request.param == "json":
        s = DocumentStore()
        monkeypatch.setattr(store_mod, "_default", s)
        yield s
        return
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    s = PostgresStore(schema=name)
    monkeypatch.setattr(store_mod, "_default", s)
    yield s
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture
def api(st):
    return TestClient(app)


def save(api, data_text="Keep capital safe", version=None):
    data = {"goals": [{"key": "returnRequirements", "title": "Return Requirements", "bullets": [data_text]}]}
    r = api.post(f"{U}/ips/jft", json={"data": data, "version": version, "status": "Draft"})
    assert r.status_code == 200, r.text
    return r.json()["ips"]["version"]


def test_no_ips_blocks_send_and_status_is_no_ips(api):
    r = api.post(f"{U}/ips-send/jft", json={"version": None})
    assert r.status_code == 409 and r.json() == {"detail": "Generate an IPS first"}
    g = api.get(f"{U}/ips-send/jft").json()
    assert g["status"] == "No IPS" and g["sent"] is False and g["message"] == "Generate an IPS first" and g["latestVersion"] is None
    assert api.get(f"{U}/ips-send/jft/snapshot").status_code == 404


def test_send_ok_has_timestamp_with_time_and_flips_status(api):
    v = save(api)
    assert api.get(f"{U}/ips-send/jft").json()["status"] == "Draft"
    r = api.post(f"{U}/ips-send/jft", json={"version": None})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "Sent to PM" and j["version"] == v
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\+00:00|Z)", j["sentAt"])
    assert isinstance(j["emptySections"], list)
    g = api.get(f"{U}/ips-send/jft").json()
    assert g == {"sent": True, "status": "Sent to PM", "sentVersion": v, "sentAt": j["sentAt"], "latestVersion": v,
                 "outdated": False, "message": g["message"]}


def test_empty_sections_listed(api):
    save(api)
    es = api.post(f"{U}/ips-send/jft", json={}).json()["emptySections"]
    assert "Return Requirements" not in es
    assert "Investment Time Horizon" in es and "Client risk profile" in es and "3L buckets and explanation" in es
    assert any(e.startswith("Investment philosophy") for e in es)


def test_unknown_version_404(api):
    save(api)
    assert api.post(f"{U}/ips-send/jft", json={"version": 99}).status_code == 404
    assert api.get(f"{U}/ips-send/jft").json()["status"] == "Draft"


def test_snapshot_frozen_after_edit_and_outdated_flag(api):
    v = save(api, "original")
    api.post(f"{U}/ips-send/jft", json={"version": v})
    snap0 = api.get(f"{U}/ips-send/jft/snapshot").json()
    assert snap0["version"] == v and snap0["status"] == "Sent to PM" and snap0["data"]["goals"][0]["bullets"] == ["original"]
    assert snap0["parts"] and snap0["sentAt"]
    # RM edits the same version in place -> snapshot unchanged, outdated
    save(api, "edited", version=v)
    assert api.get(f"{U}/ips-send/jft/snapshot").json() == snap0
    g = api.get(f"{U}/ips-send/jft").json()
    assert g["status"] == "Sent to PM" and g["outdated"] is True
    assert g["message"] == f"The PM has an older version (v{v}). Send the updated version?"
    # a new version also makes it outdated; resending replaces the snapshot
    v2 = save(api, "newer")
    g = api.get(f"{U}/ips-send/jft").json()
    assert g["outdated"] is True and g["latestVersion"] == v2 and g["sentVersion"] == v
    assert api.get(f"{U}/ips-send/jft/snapshot").json() == snap0
    api.post(f"{U}/ips-send/jft", json={"version": None})
    s2 = api.get(f"{U}/ips-send/jft/snapshot").json()
    assert s2["version"] == v2 and s2["data"]["goals"][0]["bullets"] == ["newer"]
    assert api.get(f"{U}/ips-send/jft").json()["outdated"] is False


def test_failure_keeps_draft_then_retry_succeeds(api, monkeypatch):
    save(api)

    def boom(client_id, record):
        raise RuntimeError("notify down")
    monkeypatch.setattr(ep, "notify_pm", boom)
    r = api.post(f"{U}/ips-send/jft", json={})
    assert r.status_code == 503 and r.json() == {"sent": False, "message": "Not sent. Try again."}
    assert api.get(f"{U}/ips-send/jft").json()["status"] == "Draft"
    assert api.get(f"{U}/ips-send/jft/snapshot").status_code == 404
    monkeypatch.setattr(ep, "notify_pm", ep.default_notify_pm)
    assert api.post(f"{U}/ips-send/jft", json={}).status_code == 200
    assert api.get(f"{U}/ips-send/jft").json()["status"] == "Sent to PM"


def test_failure_on_resend_keeps_previous_snapshot(api, monkeypatch):
    v = save(api, "first")
    api.post(f"{U}/ips-send/jft", json={})
    save(api, "second")
    monkeypatch.setenv("IPS_SEND_FAIL", "1")
    assert api.post(f"{U}/ips-send/jft", json={}).status_code == 503
    s = api.get(f"{U}/ips-send/jft/snapshot").json()
    assert s["version"] == v and s["data"]["goals"][0]["bullets"] == ["first"]


def test_withdraw_after_send_keeps_content(api):
    v = save(api, "keep me")
    api.post(f"{U}/ips-send/jft", json={})
    assert api.delete(f"{U}/ips-send/jft").json() == {"status": "Draft"}
    g = api.get(f"{U}/ips-send/jft").json()
    assert g["status"] == "Draft" and g["sent"] is False and g["sentVersion"] is None
    assert api.get(f"{U}/ips-send/jft/snapshot").status_code == 404
    assert api.get(f"{U}/ips/jft").json()["versions"][0]["data"]["goals"][0]["bullets"] == ["keep me"]
    assert api.delete(f"{U}/ips-send/jft").json() == {"status": "Draft"}  # idempotent
    assert v == 1 or v >= 1


def test_book_isolation_and_per_client_state(api, st):
    save(api)
    for path in ("post", "get", "delete"):
        r = getattr(api, path)(f"{U}/ips-send/dso", **({"json": {}} if path == "post" else {}))
        assert r.status_code == 403
    assert api.get(f"{U}/ips-send/dso/snapshot").status_code == 403
    st.set_in_book("dso", True)
    api.post(f"{U}/ips-send/jft", json={}, headers={"X-RM-Id": "isabel"})
    assert api.get(f"{U}/ips-send/dso").json()["status"] == "Draft"  # jft's send does not leak
    assert api.get(f"{U}/ips-send/dso/snapshot").status_code == 404
    assert api.get(f"{U}/ips-send/jft/snapshot").json()["rmId"] == "isabel"


def test_store_down_returns_503(api, st, monkeypatch):
    save(api)

    def down(*a, **k):
        raise StoreUnavailableError("down")
    monkeypatch.setattr(st, "send_ips_to_pm", down)
    r = api.post(f"{U}/ips-send/jft", json={})
    assert r.status_code == 503 and r.json()["sent"] is False and r.json()["message"] == "Not sent. Try again."
    monkeypatch.setattr(st, "get_ips_send", down)
    monkeypatch.setattr(st, "withdraw_ips_send", down)
    assert api.get(f"{U}/ips-send/jft").status_code == 503
    assert api.get(f"{U}/ips-send/jft/snapshot").status_code == 503
    assert api.delete(f"{U}/ips-send/jft").status_code == 503
