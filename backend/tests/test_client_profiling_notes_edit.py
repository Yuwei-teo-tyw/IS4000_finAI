"""PUT /meeting-notes/{client_id}/{note_id} edits one client's note (json store)."""
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DEFAULT_DATA_DIR, DocumentStore
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_STORE", "json")
    d = tmp_path / "data"
    shutil.copytree(DEFAULT_DATA_DIR, d)
    st = DocumentStore(d)
    for c in st.list_clients():
        st.set_in_book(c.id, True)  # editing tests, not the book gate
    monkeypatch.setattr(store_mod, "_default", st)
    return TestClient(app)


def _first_note(client):
    notes = client.get("/agents/client-profiling/meeting-notes/jfr").json()
    assert notes
    return notes[0]


def test_edit_updates_and_persists(client):
    n = _first_note(client)
    r = client.put(f"/agents/client-profiling/meeting-notes/jfr/{n['id']}", json={"title": "New title", "original_text": "Edited text. Second."})
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == n["id"] and j["clientId"] == "jfr" and j["title"] == "New title" and j["originalText"] == "Edited text. Second."
    assert {"id", "clientId", "date", "title", "sourceFile", "originalText", "summary", "checklist", "indexing"} <= set(j)
    again = _first_note(client)
    assert again["title"] == "New title"


def test_wrong_client_or_unknown_note_404(client):
    n = _first_note(client)
    body = {"title": "t", "original_text": "x"}
    assert client.put(f"/agents/client-profiling/meeting-notes/ser/{n['id']}", json=body).status_code == 404
    assert client.put("/agents/client-profiling/meeting-notes/jfr/nope", json=body).status_code == 404
    assert _first_note(client)["title"] == n["title"]


def test_validation(client):
    n = _first_note(client)
    u = f"/agents/client-profiling/meeting-notes/jfr/{n['id']}"
    assert client.put(u, json={"title": "", "original_text": "x"}).status_code == 422
    assert client.put(u, json={"title": "t", "original_text": ""}).status_code == 422
    assert client.put(u, json={"title": "t" * 201, "original_text": "x"}).status_code == 422
    assert client.put(u, json={"title": "t", "original_text": "x" * 20001}).status_code == 422
