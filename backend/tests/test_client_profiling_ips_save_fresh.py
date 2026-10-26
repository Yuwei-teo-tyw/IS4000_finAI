"""IS-83: DB-free coverage of save-time IPS vectorization ACs (fake PG connection + JSON store)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import embeddings
from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.ips_answer import answer_ips_question
from app.agents.client_profiling.store import DocumentStore, IpsPartDoc, IpsVersion
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling"
OLD = [{"part": 1, "title": "Objectives", "body": "Capital growth with moderate risk."}]
NEW = [{"part": 1, "title": "Objectives", "body": "Capital preservation with a FRESHMARKER 7m reserve."}]


class FakeConn:
    def __init__(self, log, rows=None):
        self.log, self.rows = log, rows or []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params=None):
        self.log.append(" ".join(str(q).split()))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def _pg(log, ips, rows=None):
    s = object.__new__(PostgresStore)
    s.vector_enabled = True
    s._connect = lambda: FakeConn(log, rows)
    s.get_ips_versions = lambda cid: [ips]
    s.latest_ips = lambda cid: (ips, ips.version)
    return s


def _ips():
    return IpsVersion(client_id="c", version=3, status="Active", issued_on="2026-01-01", author="a", summary="",
                      parts=[IpsPartDoc(part=1, title="Obj", body="Growth."), IpsPartDoc(part=2, title="Liq", body="Cash.")])


@pytest.fixture
def jstore(monkeypatch):
    s = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", s)
    return s


def test_chunks_tagged_with_client_version_part_only_in_ips_table(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_documents", lambda t: [[0.0] * 768 for _ in t])
    log = []
    assert _pg(log, _ips()).index_ips("c", 3) is True
    assert all("cp_note_chunks" not in q for q in log)
    ins = [q for q in log if q.startswith("INSERT")]
    assert len(ins) >= 2 and all("cp_ips_chunks (client_id, version, part_n" in q for q in ins)


def test_unchanged_resave_replaces_chunks_no_duplicates(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_documents", lambda t: [[0.0] * 768 for _ in t])
    log = []
    _pg(log, _ips()).index_ips("c", 3)
    assert log[0].startswith("DELETE FROM cp_ips_chunks") and "version = %s" in log[0]  # delete-then-insert per version


def test_stale_versions_removed_only_from_ips_table():
    log = []
    _pg(log, _ips()).drop_stale_ips_chunks("c", 3)
    assert len(log) == 1 and "DELETE FROM cp_ips_chunks" in log[0] and "version <> %s" in log[0] and "cp_note" not in log[0]


def test_embedding_down_leaves_unchunked_then_next_question_reindexes(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_documents", lambda t: None)
    assert _pg([], _ips()).index_ips("c", 3) is False
    # next IPS question: search_ips finds no chunks for the current version and backfills
    monkeypatch.setattr(embeddings, "embed_query", lambda t: [0.0] * 768)
    s = _pg([], _ips(), rows=None)
    calls = []
    s.index_ips = lambda cid, v: calls.append((cid, v))
    s.search_ips("c", "what is the liquidity need")
    assert calls == [("c", 3)]


def test_save_without_embeddings_still_saved_pending(jstore):
    j = TestClient(app).post(f"{U}/ips/jft", json={"parts": OLD}).json()
    assert j["indexing"]["message"] == "IPS saved, but not yet searchable" and len(jstore.get_ips_versions("jft")) == 1


def test_question_right_after_save_uses_new_content(jstore):
    c = TestClient(app)
    c.post(f"{U}/ips/jft", json={"parts": OLD})
    c.post(f"{U}/ips/jft", json={"version": 1, "parts": NEW})
    seen = {}

    def chat(s, u):
        seen["u"] = u
        return json.dumps({"in_scope": True, "answerable": True, "answer": "Capital preservation.", "cites": ["I1"]})
    r = answer_ips_question("What is the objective?", store_mod.get_default_store(), "jft", chat)
    assert r["status"] == "ok" and "FRESHMARKER" in seen["u"] and "Capital growth" not in seen["u"]


def test_not_in_book_message_and_nothing_indexed(jstore, monkeypatch):
    calls = []
    monkeypatch.setattr(DocumentStore, "index_ips", lambda self, *a: calls.append(a))
    r = TestClient(app).post(f"{U}/ips/jfr", json={"parts": OLD})
    assert r.status_code == 403 and r.json()["detail"] == "Client is not in your book" and calls == []
