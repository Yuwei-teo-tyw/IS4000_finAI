"""US-16: meeting notes are vectorized on upload/edit and the response reports it. Embeddings are stubbed."""
import os
import shutil
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling import embeddings, store as store_mod
from app.agents.client_profiling.store import DEFAULT_DATA_DIR, DocumentStore, MeetingNoteDoc
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints.client_profiling import router

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
BASE = "/agents/client-profiling/meeting-notes"
TEXT = b"Met the client on 2026-03-01. They want lower equity risk and a 5 year horizon for the house purchase."
app = FastAPI()
app.include_router(router)


def _vec(text: str) -> list[float]:
    v = [0.0] * 768
    for i, ch in enumerate(text.lower()):
        v[(ord(ch) + i) % 768] += 1.0
    return v


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


# ---- JSON store: compatible, no chunk counts ----
@pytest.fixture
def jclient(tmp_path, monkeypatch):
    d = tmp_path / "data"
    shutil.copytree(DEFAULT_DATA_DIR, d)
    st = DocumentStore(d)
    st.set_in_book("jfr", True)
    monkeypatch.setattr(store_mod, "_default", st)
    return TestClient(app)


def test_json_upload_and_edit_report_indexing(jclient):
    r = jclient.post(BASE, data={"client_id": "jfr"}, files={"file": ("n.txt", TEXT, "text/plain")})
    assert r.status_code == 200
    assert r.json()["indexing"] == {"status": "indexed", "chunks": None, "message": "Saved and searchable"}
    nid = r.json()["id"]
    e = jclient.put(f"{BASE}/jfr/{nid}", json={"title": "t", "original_text": "edited body text"})
    assert e.status_code == 200 and e.json()["indexing"]["status"] == "indexed"


def test_blank_rejected_and_nothing_saved(jclient):
    before = len(jclient.get(f"{BASE}/jfr").json())
    r = jclient.post(BASE, data={"client_id": "jfr"}, files={"file": ("n.txt", b"   \n  \t ", "text/plain")})
    assert r.status_code == 422
    assert len(jclient.get(f"{BASE}/jfr").json()) == before
    n = jclient.get(f"{BASE}/jfr").json()[0]
    assert jclient.put(f"{BASE}/jfr/{n['id']}", json={"title": "t", "original_text": "   \n "}).status_code == 422
    assert jclient.get(f"{BASE}/jfr").json()[0]["originalText"] == n["originalText"]


def test_client_not_in_book_403(jclient):
    st = store_mod.get_default_store()
    st.set_in_book("jfr", False)
    r = jclient.post(BASE, data={"client_id": "jfr"}, files={"file": ("n.txt", TEXT, "text/plain")})
    assert r.status_code == 403
    n = st.get_notes("jfr")[0]
    assert jclient.put(f"{BASE}/jfr/{n.id}", json={"title": "t", "original_text": "x"}).status_code == 403


# ---- Postgres store with stubbed embeddings ----
@pytest.fixture
def pg(monkeypatch):
    if not _reachable():
        pytest.skip("Postgres not reachable")
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda t: _vec(t))
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    s = PostgresStore(schema=name)
    if not s.vector_enabled:
        pytest.skip("pgvector unavailable")
    s.set_in_book("ser", True)
    monkeypatch.setattr(store_mod, "_default", s)
    yield s, name
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _count(name, table, where="true"):
    with psycopg.connect(DSN) as c:
        return c.execute(sql.SQL("SELECT count(*) FROM {}.{} WHERE " + where).format(
            sql.Identifier(name), sql.Identifier(table))).fetchone()[0]


def _texts(name, nid):
    with psycopg.connect(DSN) as c:
        return [r[0] for r in c.execute(sql.SQL("SELECT text FROM {}.cp_note_chunks WHERE note_id=%s ORDER BY chunk_idx").format(
            sql.Identifier(name)), (nid,)).fetchall()]


def test_pg_upload_indexed_then_resave_and_edit_replace(pg):
    s, name = pg
    c = TestClient(app)
    ips_before = _count(name, "cp_ips_chunks")
    r = c.post(BASE, data={"client_id": "ser"}, files={"file": ("n.txt", TEXT, "text/plain")})
    assert r.status_code == 200
    ind, nid = r.json()["indexing"], r.json()["id"]
    n = _count(name, "cp_note_chunks", f"note_id = '{nid}'")
    assert ind["status"] == "indexed" and ind["chunks"] == n >= 1
    assert ind["message"] == f"Indexed: {n} chunk{'s' if n != 1 else ''}"
    # re-save unchanged: replace, never append
    same = c.put(f"{BASE}/ser/{nid}", json={"title": "x", "original_text": TEXT.decode()})
    assert same.json()["indexing"]["chunks"] == n and _count(name, "cp_note_chunks", f"note_id = '{nid}'") == n
    # edit replaces the old chunks
    c.put(f"{BASE}/ser/{nid}", json={"title": "x", "original_text": "Completely different content about bonds."})
    assert _texts(name, nid) == ["Completely different content about bonds."]
    assert _count(name, "cp_ips_chunks") == ips_before  # notes never land in the IPS chunk table


def test_pg_embedding_down_saves_pending_then_lazy_backfill(pg, monkeypatch):
    s, name = pg
    c = TestClient(app)
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: None)
    monkeypatch.setattr(embeddings, "embed_query", lambda t: None)
    r = c.post(BASE, data={"client_id": "ser"}, files={"file": ("n.txt", TEXT, "text/plain")})
    nid = r.json()["id"]
    assert r.status_code == 200
    assert r.json()["indexing"] == {"status": "pending", "chunks": 0, "message": "Note saved, but not yet searchable"}
    assert s.get_note("ser", nid) is not None and _count(name, "cp_note_chunks", f"note_id = '{nid}'") == 0
    # an edit while the model is down must not leave stale chunks of the old text
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda t: _vec(t))
    # next question lazily re-indexes
    hits = s.search_notes("ser", "equity risk horizon")
    assert hits and _count(name, "cp_note_chunks", f"note_id = '{nid}'") >= 1


def test_pg_failed_edit_clears_stale_chunks(pg, monkeypatch):
    s, name = pg
    c = TestClient(app)
    nid = c.post(BASE, data={"client_id": "ser"}, files={"file": ("n.txt", TEXT, "text/plain")}).json()["id"]
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: (_ for _ in ()).throw(RuntimeError("down")))
    e = c.put(f"{BASE}/ser/{nid}", json={"title": "x", "original_text": "new text after the model went down"})
    assert e.status_code == 200 and e.json()["indexing"]["status"] == "pending"
    assert _count(name, "cp_note_chunks", f"note_id = '{nid}'") == 0


def test_pg_retry_on_status_indexes_when_model_back(pg, monkeypatch):
    s, name = pg
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: None)
    note = s.add_note(MeetingNoteDoc(id="note_up_1", client_id="ser", date="2026-01-01", title="t", source_file="f.txt", text="Some meeting text here."))
    assert s.note_indexing("ser", note.id) == {"status": "pending", "chunks": 0}
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [_vec(t) for t in texts])
    assert s.note_indexing("ser", note.id) == {"status": "indexed", "chunks": 1}


def test_pg_not_in_book_403_no_chunks(pg):
    s, name = pg
    s.set_in_book("ser", False)
    before = _count(name, "cp_note_chunks")
    r = TestClient(app).post(BASE, data={"client_id": "ser"}, files={"file": ("n.txt", TEXT, "text/plain")})
    assert r.status_code == 403 and _count(name, "cp_note_chunks") == before
