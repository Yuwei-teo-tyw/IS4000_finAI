"""US-17: saving an IPS indexes it (current version only). JSON-store/stub tests always run; the Postgres tests
(real throwaway schema, fake embeddings) skip when Postgres/pgvector is unavailable."""
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
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling"
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
PARTS = [{"part": 1, "title": "Objectives", "body": "Capital growth with moderate risk."},
         {"part": 2, "title": "Liquidity", "body": "Keep S$3m for a house deposit."}]


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


def _vec(text: str) -> list[float]:
    v = [0.0] * 768
    for i, ch in enumerate(text.lower()):
        v[(ord(ch) + i) % 768] += 1.0
    return v


@pytest.fixture
def jstore(monkeypatch):
    s = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", s)
    return s


def test_json_store_save_is_pending_and_versions_supersede(jstore):
    c = TestClient(app)
    r = c.post(f"{U}/ips/jft", json={"parts": PARTS, "author": "Isabel"})
    assert r.status_code == 200
    j = r.json()
    assert j["indexing"] == {"status": "pending", "chunks": 0, "message": "IPS saved, but not yet searchable"}
    assert j["ips"]["version"] == 1 and j["ips"]["status"] == "Active"
    r2 = c.post(f"{U}/ips/jft", json={"parts": PARTS}).json()
    assert r2["ips"]["version"] == 2
    assert [(v.version, v.status) for v in jstore.get_ips_versions("jft")] == [(2, "Active"), (1, "Superseded")]
    r3 = c.post(f"{U}/ips/jft", json={"version": 2, "parts": PARTS[:1], "summary": "edited"}).json()
    assert r3["ips"]["version"] == 2 and len(r3["ips"]["parts"]) == 1 and len(jstore.get_ips_versions("jft")) == 2


def test_not_in_book_403_nothing_saved_or_indexed(jstore, monkeypatch):
    calls = []
    monkeypatch.setattr(DocumentStore, "index_ips", lambda self, *a: calls.append(a))
    before = len(jstore.get_ips_versions("jfr"))
    r = TestClient(app).post(f"{U}/ips/jfr", json={"parts": PARTS})
    assert r.status_code == 403 and len(jstore.get_ips_versions("jfr")) == before
    assert calls == []
    assert TestClient(app).post(f"{U}/ips/jft", json={"version": 9, "parts": PARTS}).status_code == 404
    assert TestClient(app).post(f"{U}/ips/jft", json={"parts": []}).status_code == 422


def test_indexed_response_and_stale_cleanup_with_stub_index(jstore, monkeypatch):
    dropped = []
    monkeypatch.setattr(DocumentStore, "index_ips", lambda self, cid, v: True)
    monkeypatch.setattr(DocumentStore, "count_ips_chunks", lambda self, cid, v: 5)
    monkeypatch.setattr(DocumentStore, "drop_stale_ips_chunks", lambda self, cid, keep: dropped.append(keep))
    j = TestClient(app).post(f"{U}/ips/jft", json={"parts": PARTS}).json()
    assert j["indexing"] == {"status": "indexed", "chunks": 5, "message": "IPS v1 indexed"} and dropped == [1]


def test_index_failure_still_saves(jstore, monkeypatch):
    monkeypatch.setattr(DocumentStore, "index_ips", lambda self, cid, v: False)
    j = TestClient(app).post(f"{U}/ips/jft", json={"parts": PARTS}).json()
    assert j["indexing"]["status"] == "pending" and len(jstore.get_ips_versions("jft")) == 1


def test_draft_save_is_not_current_so_not_indexed(jstore, monkeypatch):
    monkeypatch.setattr(DocumentStore, "index_ips", lambda self, cid, v: True)
    c = TestClient(app)
    c.post(f"{U}/ips/jft", json={"parts": PARTS})
    j = c.post(f"{U}/ips/jft", json={"parts": PARTS, "status": "Draft"}).json()
    assert j["ips"]["status"] == "Draft" and j["indexing"]["status"] == "pending"
    assert [v.status for v in jstore.get_ips_versions("jft")] == ["Draft", "Active"]


# ---------------- Postgres ----------------
pg_only = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda t: _vec(t))
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    s = PostgresStore(schema=name)
    if not s.vector_enabled:
        pytest.skip("pgvector unavailable")
    monkeypatch.setattr(store_mod, "_default", s)
    yield s, name
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _count(schema, table, where="true"):
    with psycopg.connect(DSN) as c:
        return c.execute(sql.SQL("SELECT count(*) FROM {}.{} WHERE " + where).format(
            sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]


@pg_only
def test_pg_save_indexes_only_current_version_no_duplicates(pg):
    s, name = pg
    c = TestClient(app)
    notes_before = _count(name, "cp_note_chunks")
    j1 = c.post(f"{U}/ips/jft", json={"parts": PARTS}).json()
    assert j1["indexing"]["status"] == "indexed" and j1["indexing"]["message"] == "IPS v1 indexed"
    n1 = j1["indexing"]["chunks"]
    assert n1 >= 2 and _count(name, "cp_ips_chunks") == n1
    c.post(f"{U}/ips/jft", json={"version": 1, "parts": PARTS})  # unchanged re-save
    assert _count(name, "cp_ips_chunks") == n1
    j2 = c.post(f"{U}/ips/jft", json={"parts": PARTS[:1]}).json()
    assert j2["indexing"]["message"] == "IPS v2 indexed"
    assert _count(name, "cp_ips_chunks", "version = 1") == 0 and _count(name, "cp_ips_chunks", "version = 2") > 0
    assert _count(name, "cp_note_chunks") == notes_before  # IPS never goes into the notes index
    hits = s.search_ips("jft", "capital growth")
    assert hits and {h["version"] for h in hits} == {2}


@pg_only
def test_pg_embedding_down_saves_pending_then_lazy_reindex(pg, monkeypatch):
    s, name = pg
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: None)
    j = TestClient(app).post(f"{U}/ips/jft", json={"parts": PARTS}).json()
    assert j["indexing"] == {"status": "pending", "chunks": 0, "message": "IPS saved, but not yet searchable"}
    assert len(s.get_ips_versions("jft")) == 1 and _count(name, "cp_ips_chunks") == 0
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    assert s.search_ips("jft", "house deposit")  # lazy backfill on the next IPS question
    assert _count(name, "cp_ips_chunks", "version = 1") > 0


@pg_only
def test_pg_not_in_book_403_nothing_indexed(pg):
    s, name = pg
    before = len(s.get_ips_versions("jfr"))
    r = TestClient(app).post(f"{U}/ips/jfr", json={"parts": PARTS})
    assert r.status_code == 403 and len(s.get_ips_versions("jfr")) == before and _count(name, "cp_ips_chunks") == 0
