"""IS-94: IPS chat history persisted per client AND per RM, capped at 100, DB-down signalled. JSON store + real PG if reachable."""
import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import IPS_CHAT_CAP, DocumentStore, StoreUnavailableError
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints.client_profiling import router

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
U = "/agents/client-profiling"
app = FastAPI()
app.include_router(router)


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(params=["json", pytest.param("pg", marks=pytest.mark.skipif(not _reachable(), reason="Postgres not reachable"))])
def store(request):
    if request.param == "json":
        yield DocumentStore()
        return
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    yield PostgresStore(schema=name)
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def test_history_scoped_per_rm_and_client(store):
    store.append_ips_chat("jft", "user", "from isabel", rm_id="isabel")
    store.append_ips_chat("jft", "user", "from bob", rm_id="bob")
    assert [m["text"] for m in store.list_ips_chat("jft", rm_id="isabel")] == ["from isabel"]
    assert [m["text"] for m in store.list_ips_chat("jft", rm_id="bob")] == ["from bob"]
    assert store.list_ips_chat("jfr", rm_id="isabel") == []
    store.clear_ips_chat("jft", rm_id="bob")
    assert store.list_ips_chat("jft", rm_id="bob") == [] and len(store.list_ips_chat("jft", rm_id="isabel")) == 1


def test_cap_drops_oldest_and_flags_truncated(store):
    last = None
    for i in range(IPS_CHAT_CAP + 1):
        last = store.append_ips_chat("jft", "user", f"m{i}", rm_id="isabel")
        assert last["truncated"] is (i == IPS_CHAT_CAP)
    rows = store.list_ips_chat("jft", rm_id="isabel")
    assert len(rows) == IPS_CHAT_CAP == 100 and rows[0]["text"] == "m1" and rows[-1]["text"] == f"m{IPS_CHAT_CAP}"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    return TestClient(app)


def H(rm):
    return {"X-RM-Id": rm}


def test_endpoints_other_rm_cannot_see(api):
    api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": "secret"}, headers=H("isabel"))
    assert [m["text"] for m in api.get(f"{U}/ips-chat/jft", headers=H("isabel")).json()["messages"]] == ["secret"]
    assert api.get(f"{U}/ips-chat/jft", headers=H("bob")).json()["messages"] == []
    assert api.get(f"{U}/ips-chat/jft?rm_id=isabel").json()["messages"][0]["text"] == "secret"  # query alternative
    api.delete(f"{U}/ips-chat/jft", headers=H("bob"))
    assert len(api.get(f"{U}/ips-chat/jft", headers=H("isabel")).json()["messages"]) == 1


def test_endpoint_truncated_flag_and_message(api):
    for i in range(IPS_CHAT_CAP):
        r = api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": f"m{i}"}, headers=H("isabel")).json()
        assert r["truncated"] is False
    r = api.post(f"{U}/ips-chat/jft", json={"role": "assistant", "text": "one more"}, headers=H("isabel")).json()
    assert r["truncated"] is True and "100" in r["message"]
    g = api.get(f"{U}/ips-chat/jft", headers=H("isabel")).json()
    assert len(g["messages"]) == 100 and g["truncated"] is True and g["messages"][0]["text"] == "m1" and g["cap"] == 100


def test_db_unreachable_signals_history_unavailable(api, monkeypatch):
    def boom(*a, **k):
        raise StoreUnavailableError("down")
    for m in ("list_ips_chat", "append_ips_chat", "clear_ips_chat"):
        monkeypatch.setattr(store_mod._default, m, boom)
    for r in (api.get(f"{U}/ips-chat/jft"), api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": "x"}),
              api.delete(f"{U}/ips-chat/jft")):
        assert r.status_code == 503 and r.json()["historyAvailable"] is False


def test_endpoint_persist_then_clear_keeps_other_rm(api):
    for rm in ("isabel", "bob"):
        api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": "q"}, headers=H(rm))
        api.post(f"{U}/ips-chat/jft", json={"role": "assistant", "text": "a", "kind": "discuss"}, headers=H(rm))
    assert [m["text"] for m in api.get(f"{U}/ips-chat/jft", headers=H("isabel")).json()["messages"]] == ["q", "a"]  # reload keeps it
    assert api.delete(f"{U}/ips-chat/jft", headers=H("isabel")).json() == {"cleared": True}
    assert api.get(f"{U}/ips-chat/jft", headers=H("isabel")).json()["messages"] == []
    assert len(api.get(f"{U}/ips-chat/jft", headers=H("bob")).json()["messages"]) == 2
