"""Client book (single RM): cp_clients.in_book in the JSON store, /book, and the DB-book gating of every route."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.endpoints.client_profiling as ep
from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DocumentStore, StoreUnavailableError
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling"


@pytest.fixture
def store(monkeypatch):
    s = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", s)
    return s


@pytest.fixture
def client(store):
    return TestClient(app)


def test_seed_book_only_jft(store):
    assert store.book_ids() == ["jft"]
    c = store.list_book()[0]
    assert (c.id, c.name, c.in_book, c.onboarding_progress, c.monitoring_progress) == ("jft", "Jane Fraser (test)", True, 0, 0)
    assert [x.id for x in store.list_clients() if x.in_book] == ["jft"]
    assert len(store.list_clients()) == 7


def test_jft_has_notes_and_no_ips(store):
    assert store.get_ips_versions("jft") == [] and store.latest_ips("jft") == (None, False)
    assert {n.id for n in store.get_notes("jft")} == {"note_jft_1013", "note_jft_1020"}
    assert {n.id for n in store.get_notes("jfr")} == {"note_1013", "note_1020"}
    assert store.search_ips("jft", "risk") is None


def test_set_in_book_and_progress(store):
    assert store.set_in_book("ser", True) and store.book_ids() == ["jft", "ser"]
    assert store.set_progress("ser", onboarding=3) and store.set_progress("ser", monitoring=40)
    r = next(c for c in store.list_book() if c.id == "ser")
    assert (r.onboarding_progress, r.monitoring_progress) == (3, 40)
    assert not store.set_progress("ghost", onboarding=1) and not store.set_in_book("ghost", True)
    with pytest.raises(ValueError):
        store.set_progress("ser", onboarding=6)
    with pytest.raises(ValueError):
        store.set_progress("ser", monitoring=101)
    assert store.set_in_book("ser", False) and store.book_ids() == ["jft"]


def test_book_endpoint(client, store):
    j = client.get(f"{U}/book").json()
    assert [c["id"] for c in j["clients"]] == ["jft"] and "message" not in j
    assert set(j["clients"][0]) == {"id", "name", "surname", "risk_category", "aum_sgd", "status",
                                    "onboarding_progress", "monitoring_progress"}
    store.set_in_book("jft", False)
    e = client.get(f"{U}/book").json()
    assert e == {"clients": [], "message": "No clients in your book"}


def test_notes_gate_403(client):
    assert client.get(f"{U}/meeting-notes/jft").status_code == 200
    r = client.get(f"{U}/meeting-notes/ser")
    assert r.status_code == 403 and r.json()["detail"] == "Client is not in your book"
    assert client.put(f"{U}/meeting-notes/ser/x", json={"title": "t", "original_text": "t"}).status_code == 403
    assert client.post(f"{U}/meeting-notes", data={"client_id": "ser"}, files={"file": ("a.txt", b"hello")}).status_code == 403
    assert client.post(f"{U}/ips-assist", json={"client_id": "ser"}).status_code == 403
    assert client.post(f"{U}/ips-assist", json={"client_id": "ghost"}).status_code == 404


def test_chat_always_uses_db_book_and_ignores_client_book(client, monkeypatch):
    seen = {}

    def fake(message, client_id, book=None, source=None, **kw):
        seen["book"] = book
        return ep.ToolResult(status="ok", tool="x", message="m")
    monkeypatch.setattr(ep, "handle_chat", fake)
    assert client.post(f"{U}/chat", json={"message": "hi", "book": ["ser", "dso"], "rm_id": "isabel"}).status_code == 200
    assert seen["book"] == ["jft"]
    client.post(f"{U}/chat", json={"message": "hi"})
    assert seen["book"] == ["jft"]


def test_chat_denies_non_book_client_before_any_model_call(client, store, monkeypatch):
    from app.agents.client_profiling import service
    calls = []
    monkeypatch.setattr(service, "default_chat", lambda *a, **k: calls.append(a) or "x", raising=False)
    body = {"message": "Summarise Sergio Ermotti's notes", "client_id": "ser", "book": ["ser"]}
    r = client.post(f"{U}/chat", json=body).json()
    assert r["status"] != "ok" and calls == []
    store.set_in_book("jft", False)  # empty book: every client question is denied
    r = client.post(f"{U}/chat", json={"message": "Summarise Jane Fraser's notes", "client_id": "jft"}).json()
    assert r["status"] != "ok" and calls == []


def test_chat_answers_for_jft(client, monkeypatch):
    from app.agents.client_profiling.service import handle_chat as real

    def fake_answer(messages, **kw):
        return "Jane Fraser asked about her conservative profile."
    monkeypatch.setattr(ep, "handle_chat", lambda m, c, book=None, source=None, **kw: real(m, c, book=book, source=source,
                                                                                    answer_chat=fake_answer, router_chat=fake_answer))
    r = client.post(f"{U}/chat", json={"message": "What did Jane Fraser say about risk?", "client_id": "jft"}).json()
    assert r["status"] != "unavailable" and "not in your book" not in r["message"]


def test_db_down(monkeypatch):
    class Down(DocumentStore):
        def list_book(self):
            raise StoreUnavailableError("down")

        def book_ids(self):
            raise StoreUnavailableError("down")

    monkeypatch.setattr(store_mod, "_default", Down())
    c = TestClient(app)
    r = c.get(f"{U}/book")
    assert r.status_code == 503 and r.json() == {"detail": "The client database is unavailable."}
    r = c.post(f"{U}/chat", json={"message": "hi", "client_id": "jft"}).json()
    assert r["tool"] == "routing_unavailable" and "unavailable" in r["message"]
    assert c.get(f"{U}/meeting-notes/jft").status_code == 503
