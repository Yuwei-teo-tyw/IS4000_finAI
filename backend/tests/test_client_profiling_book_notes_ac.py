"""IS-81 / IS-82 acceptance criteria that must run without Postgres: JSON-store behaviour plus the PostgresStore chunk
logic exercised against an in-memory fake connection (no DB, no model)."""
import re
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import embeddings, retrieval, store as store_mod
from app.agents.client_profiling.store import DEFAULT_DATA_DIR, DocumentStore, MeetingNoteDoc
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling"
TEXT = b"Met the client on 2026-03-01. They want lower equity risk and a 5 year horizon for the house purchase."


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = tmp_path / "data"
    shutil.copytree(DEFAULT_DATA_DIR, d)
    s = DocumentStore(d)
    monkeypatch.setattr(store_mod, "_default", s)
    return s


@pytest.fixture
def client(store):
    return TestClient(app)


# ---------------- IS-81 ----------------
def test_book_lists_only_assigned_clients_with_both_progress_fields(client, store):
    store.set_in_book("ser", True)
    store.set_progress("ser", onboarding=2, monitoring=10)
    rows = {c["id"]: c for c in client.get(f"{U}/book").json()["clients"]}
    assert set(rows) == {"jft", "ser"}  # not the other 5 seeded clients
    assert (rows["ser"]["onboarding_progress"], rows["ser"]["monitoring_progress"]) == (2, 10)


def test_notes_only_client_progress_zero_and_notes_readable(client, store):
    j = client.get(f"{U}/book").json()["clients"][0]
    assert (j["id"], j["onboarding_progress"], j["monitoring_progress"]) == ("jft", 0, 0)
    assert store.latest_ips("jft") == (None, False) and store.get_notes("jft")
    assert client.get(f"{U}/meeting-notes/jft").status_code == 200


def test_client_without_notes_or_ips_is_progress_zero_not_error(client, store):
    cid = next(c.id for c in store.list_clients() if not store.get_notes(c.id) and not store.get_ips_versions(c.id)) \
        if any(not store.get_notes(c.id) and not store.get_ips_versions(c.id) for c in store.list_clients()) else None
    if cid is None:  # none seeded: strip one client of everything
        cid = "dso"
        store._notes = [n for n in store._notes if n.client_id != cid]
    store.set_in_book(cid, True)
    row = next(c for c in client.get(f"{U}/book").json()["clients"] if c["id"] == cid)
    assert (row["onboarding_progress"], row["monitoring_progress"]) == (0, 0)
    r = client.get(f"{U}/meeting-notes/{cid}")
    assert r.status_code == 200 and (r.json() == [] or isinstance(r.json(), list))


def test_empty_book_message_and_every_client_question_denied(client, store, monkeypatch):
    from app.agents.client_profiling import service
    for c in store.list_clients():
        store.set_in_book(c.id, False)
    assert client.get(f"{U}/book").json() == {"clients": [], "message": "No clients in your book"}
    calls = []
    monkeypatch.setattr(service, "default_chat", lambda *a, **k: calls.append(a) or "x", raising=False)
    for cid, name in (("jft", "Jane Fraser"), ("ser", "Sergio Ermotti")):
        r = client.post(f"{U}/chat", json={"message": f"Summarise {name}'s notes", "client_id": cid}).json()
        assert r["status"] != "ok"
    assert calls == []


# ---------------- IS-82 (JSON store) ----------------
def test_edit_date_title_text_all_persist(client, store):
    store.set_in_book("jfr", True)
    n = client.get(f"{U}/meeting-notes/jfr").json()[0]
    r = client.put(f"{U}/meeting-notes/jfr/{n['id']}", json={"title": "T2", "original_text": "New body.", "date": "2026-02-02"})
    assert r.status_code == 200 and r.json()["date"] == "2026-02-02" and r.json()["title"] == "T2"
    got = store.get_note("jfr", n["id"])
    assert (got.date, got.title, got.text) == ("2026-02-02", "T2", "New body.")
    assert client.put(f"{U}/meeting-notes/jfr/{n['id']}", json={"title": "T", "original_text": "x", "date": "bad"}).status_code == 422


def test_question_right_after_upload_and_edit_uses_new_content(client, store):
    store.set_in_book("jfr", True)
    up = client.post(f"{U}/meeting-notes", data={"client_id": "jfr"},
                     files={"file": ("n.txt", b"The client asked about a zebra farm investment.", "text/plain")}).json()
    n = store.get_note("jfr", up["id"])
    assert retrieval.best_passages(n.text, "zebra farm")
    client.put(f"{U}/meeting-notes/jfr/{up['id']}", json={"title": "t", "original_text": "Now discussing giraffe sanctuary donations."})
    n = store.get_note("jfr", up["id"])
    assert retrieval.best_passages(n.text, "giraffe sanctuary") and "zebra" not in n.text


def test_resave_unchanged_json_note_no_duplicates(client, store):
    store.set_in_book("jfr", True)
    up = client.post(f"{U}/meeting-notes", data={"client_id": "jfr"}, files={"file": ("n.txt", TEXT, "text/plain")}).json()
    before = len(store.get_notes("jfr"))
    for _ in range(2):
        client.put(f"{U}/meeting-notes/jfr/{up['id']}", json={"title": up["title"], "original_text": TEXT.decode()})
    assert len(store.get_notes("jfr")) == before


def test_upload_not_in_book_message(client):
    r = client.post(f"{U}/meeting-notes", data={"client_id": "ser"}, files={"file": ("n.txt", TEXT, "text/plain")})
    assert r.status_code == 403 and r.json()["detail"] == "Client is not in your book"


def test_indexing_messages(client, store, monkeypatch):
    import app.endpoints.client_profiling as ep
    store.set_in_book("jfr", True)
    nid = client.post(f"{U}/meeting-notes", data={"client_id": "jfr"}, files={"file": ("n.txt", TEXT, "text/plain")}).json()["id"]
    note = store.get_note("jfr", nid)
    monkeypatch.setattr(store, "note_indexing", lambda c, n: {"status": "indexed", "chunks": 4}, raising=False)
    assert ep._indexing(store, note)["message"] == "Indexed: 4 chunks"
    monkeypatch.setattr(store, "note_indexing", lambda c, n: {"status": "indexed", "chunks": 1}, raising=False)
    assert ep._indexing(store, note)["message"] == "Indexed: 1 chunk"
    monkeypatch.setattr(store, "note_indexing", lambda c, n: {"status": "pending", "chunks": 0}, raising=False)
    assert ep._indexing(store, note) == {"status": "pending", "chunks": 0, "message": "Note saved, but not yet searchable"}


# ---------------- IS-82 (Postgres store logic on an in-memory fake) ----------------
class FakeDb:
    """Emulates only the cp_note_chunks / cp_ips_chunks / cp_meeting_notes statements _reindex_note & note_indexing use."""

    def __init__(self):
        self.note_chunks: dict[tuple[str, int], tuple[str, str]] = {}  # (note_id, idx) -> (client_id, text)
        self.ips_chunks: list = []
        self.notes: dict[str, dict] = {}

    def connect(self):
        db = self

        class Cur:
            def __init__(s, rows=None):
                s.rows = rows or []

            def fetchone(s):
                return s.rows[0] if s.rows else None

            def fetchall(s):
                return s.rows

        class Conn:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def execute(s, q, p=()):
                q = " ".join(q.split())
                if q.startswith("DELETE FROM cp_note_chunks"):
                    db.note_chunks = {k: v for k, v in db.note_chunks.items() if not (k[0] == p[0] and v[0] == p[1])}
                elif q.startswith("INSERT INTO cp_note_chunks"):
                    if (p[0], p[2]) in db.note_chunks:
                        raise RuntimeError("unique violation")
                    db.note_chunks[(p[0], p[2])] = (p[1], p[3])
                elif q.startswith("SELECT count(*) AS n FROM cp_note_chunks"):
                    return Cur([{"n": sum(1 for k, v in db.note_chunks.items() if k[0] == p[0] and v[0] == p[1])}])
                elif "cp_ips_chunks" in q:
                    raise AssertionError("note code must never touch the IPS vector table")
                else:
                    raise AssertionError(f"unexpected sql: {q}")
                return Cur()

        return Conn()


@pytest.fixture
def pg(monkeypatch):
    db = FakeDb()
    s = PostgresStore.__new__(PostgresStore)
    s.vector_enabled = True
    s._connect = db.connect
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [[0.1] * 768 for _ in texts])
    s.get_note = lambda c, n: MeetingNoteDoc(**db.notes[n]) if n in db.notes else None
    return s, db


LONG = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(4))


def _texts(db, nid):
    return [v[1] for k, v in sorted(db.note_chunks.items()) if k[0] == nid]


def test_pg_chunks_embeds_and_reports_count(pg):
    s, db = pg
    db.notes["n1"] = dict(id="n1", client_id="c", date="2026-01-01", title="t", text=LONG)
    assert s._reindex_note("c", "n1", LONG) is True
    chunks = embeddings.chunk_text(LONG)
    assert len(chunks) > 1 and _texts(db, "n1") == chunks
    assert s.note_indexing("c", "n1") == {"status": "indexed", "chunks": len(chunks)}


def test_pg_resave_unchanged_never_duplicates_and_edit_replaces(pg):
    s, db = pg
    s._reindex_note("c", "n1", LONG)
    n = len(db.note_chunks)
    s._reindex_note("c", "n1", LONG)
    s._reindex_note("c", "n1", LONG)
    assert len(db.note_chunks) == n
    s._reindex_note("c", "n1", "Short new text.")
    assert _texts(db, "n1") == ["Short new text."]


def test_pg_embedding_unavailable_leaves_no_chunks_then_lazy_retry(pg, monkeypatch):
    s, db = pg
    s._reindex_note("c", "n1", LONG)
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: None)
    db.notes["n1"] = dict(id="n1", client_id="c", date="2026-01-01", title="t", text="Edited text.")
    assert s._reindex_note("c", "n1", "Edited text.") is False and _texts(db, "n1") == []  # stale chunks gone
    assert s.note_indexing("c", "n1") == {"status": "pending", "chunks": 0}
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [[0.2] * 768 for _ in texts])
    assert s.note_indexing("c", "n1") == {"status": "indexed", "chunks": 1}  # retry succeeds


def test_pg_embedding_raises_is_pending_not_error(pg, monkeypatch):
    s, db = pg
    monkeypatch.setattr(embeddings, "embed_documents", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    assert s._reindex_note("c", "n1", LONG) is False and db.note_chunks == {}


def test_pg_blank_text_creates_no_chunks(pg):
    s, db = pg
    s._reindex_note("c", "n1", "   \n  ")
    assert db.note_chunks == {}
    assert embeddings.chunk_text("  \n\t ") == []


def test_pg_update_note_sql_edits_date_and_reindexes(pg, monkeypatch):
    s, db = pg
    seen = {}

    class C:
        def __enter__(s_):
            return s_

        def __exit__(s_, *a):
            return False

        def execute(s_, q, p=()):
            if "UPDATE" in q:
                seen["q"], seen["p"] = q, p

            class R:
                def fetchone(_):
                    return {"id": "n1", "client_id": "c", "note_date": "2026-02-02", "title": "T", "source_file": "f", "text": "Fresh."}
            return R()
    s._connect = lambda: C()
    out = s.update_note("c", "n1", title="T", text="Fresh.", date="2026-02-02")
    assert "note_date = COALESCE" in seen["q"] and "2026-02-02" in seen["p"] and out.date == "2026-02-02"
