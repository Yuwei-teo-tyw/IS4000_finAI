"""Separate vector stores: cp_ips_chunks (IPS, current version only) vs cp_note_chunks (notes). Real Postgres in a
throwaway schema; skipped when Postgres/pgvector is unavailable. Embeddings are faked (deterministic)."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app.agents.client_profiling import embeddings
from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


def _vec(text: str) -> list[float]:
    v = [0.0] * 768
    for i, ch in enumerate(text.lower()):
        v[(ord(ch) + i) % 768] += 1.0
    return v


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda t: _vec(t))
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    s = PostgresStore(schema=name)
    if not s.vector_enabled:
        pytest.skip("pgvector unavailable")
    yield s, name
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _rows(schema, table, where="true"):
    with psycopg.connect(DSN) as c:
        return c.execute(sql.SQL("SELECT * FROM {}.{} WHERE " + where).format(
            sql.Identifier(schema), sql.Identifier(table))).fetchall()


def test_book_columns_seed_and_progress_pg(pg):
    s, name = pg
    assert s.book_ids() == ["jft"]
    b = s.list_book()[0]
    assert (b.in_book, b.onboarding_progress, b.monitoring_progress) == (True, 0, 0)
    assert [c.id for c in s.list_clients() if c.in_book] == ["jft"]
    assert s.get_ips_versions("jft") == [] and len(s.get_notes("jft")) == 2
    assert s.set_in_book("ser", True) and s.book_ids() == ["jft", "ser"]
    assert s.set_progress("ser", onboarding=2, monitoring=55)
    r = next(c for c in s.list_book() if c.id == "ser")
    assert (r.onboarding_progress, r.monitoring_progress) == (2, 55)
    assert s.set_in_book("ser", False) and s.book_ids() == ["jft"]
    assert not s.set_progress("ghost", onboarding=1) and not s.set_in_book("ghost", True)
    with pytest.raises(ValueError):
        s.set_progress("ser", onboarding=9)
    PostgresStore(schema=name, seed=True)  # re-init must not flip anyone else
    assert s.book_ids() == ["jft"]


def test_legacy_book_table_migrated_and_dropped(monkeypatch):
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
            c.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(name)))
            c.execute("CREATE TABLE cp_clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, surname TEXT NOT NULL DEFAULT '', "
                      "risk_category TEXT, risk_cap INTEGER, aum_sgd DOUBLE PRECISION, status TEXT)")
            c.execute("INSERT INTO cp_clients (id, name) VALUES ('ser','S')")
            c.execute("CREATE TABLE cp_client_book (rm_id TEXT, client_id TEXT, assigned_on DATE)")
            c.execute("INSERT INTO cp_client_book VALUES ('old','ser', current_date)")
        s = PostgresStore(schema=name)
        assert s.book_ids() == ["jft"]  # ser stays out of the book; only jft is turned on
        assert s.get_client("ser").in_book is False
        with psycopg.connect(DSN) as c:
            assert c.execute("SELECT to_regclass(%s)", (f"{name}.cp_client_book",)).fetchone()[0] is None
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def test_ips_search_current_version_and_isolation(pg):
    s, name = pg
    hits = s.search_ips("ser", "risk tolerance and allocation", k=3)
    ips, _ = s.latest_ips("ser")
    assert hits and all(h["version"] == ips.version and set(h) == {"part_n", "version", "text", "score"} for h in hits)
    assert _rows(name, "cp_ips_chunks", "client_id <> 'ser'") == []   # only the searched client was indexed
    assert _rows(name, "cp_note_chunks") == []                        # IPS search never touched note chunks
    assert s.search_ips("jft", "anything") is None                    # no IPS


def test_notes_search_does_not_touch_ips_chunks(pg):
    s, name = pg
    assert s.search_notes("jft", "risk averse")
    assert _rows(name, "cp_ips_chunks") == []
    assert _rows(name, "cp_note_chunks", "client_id <> 'jft'") == []


def test_reindex_replaces_and_failure_leaves_unchunked(pg, monkeypatch):
    s, name = pg
    assert s.index_ips("ser", 2) is True
    n1 = len(_rows(name, "cp_ips_chunks", "version = 2"))
    assert s.index_ips("ser", 2) is True and len(_rows(name, "cp_ips_chunks", "version = 2")) == n1
    monkeypatch.setattr(embeddings, "embed_documents", lambda t: None)
    assert s.index_ips("ser", 2) is False
    assert _rows(name, "cp_ips_chunks", "version = 2") == []
    assert s.index_ips("ser", 99) is False


def test_json_store_search_ips_none():
    assert DocumentStore().search_ips("ser", "x") is None
