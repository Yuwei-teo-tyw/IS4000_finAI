"""IPS chat history on the JSON store and a real-Postgres schema."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


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


def test_append_list_order_and_shape(store):
    a = store.append_ips_chat("jfr", "user", "why B?")
    b = store.append_ips_chat("jfr", "assistant", "Because ...", kind="discuss", meta={"stance": "info"})
    assert set(a) == {"id", "role", "kind", "text", "ts", "meta", "truncated"} and a["kind"] == "chat" and a["meta"] is None
    rows = store.list_ips_chat("jfr")
    assert [r["id"] for r in rows] == [a["id"], b["id"]] and rows[1]["meta"] == {"stance": "info"}
    assert "T" in rows[0]["ts"]


def test_limit_returns_latest_oldest_first(store):
    for i in range(5):
        store.append_ips_chat("jfr", "user", f"m{i}")
    assert [r["text"] for r in store.list_ips_chat("jfr", limit=3)] == ["m2", "m3", "m4"]


def test_clear_is_per_client(store):
    store.append_ips_chat("jfr", "user", "x")
    store.append_ips_chat("jft", "user", "y")
    store.clear_ips_chat("jfr")
    assert store.list_ips_chat("jfr") == [] and len(store.list_ips_chat("jft")) == 1


def test_invalid_role_or_kind_rejected(store):
    with pytest.raises(ValueError):
        store.append_ips_chat("jfr", "system", "x")
    with pytest.raises(ValueError):
        store.append_ips_chat("jfr", "user", "x", kind="other")
