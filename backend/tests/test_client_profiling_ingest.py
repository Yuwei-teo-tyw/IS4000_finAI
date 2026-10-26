"""Uploads are ingested into the meeting-notes store and are immediately readable by the agent."""
import io
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DEFAULT_DATA_DIR, DocumentStore
from app.endpoints.client_profiling import router


def make_pdf(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO(); w.write(buf)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "data"; shutil.copytree(DEFAULT_DATA_DIR, d)
    s = DocumentStore(d)
    for c in s.list_clients():
        s.set_in_book(c.id, True)  # these tests exercise ingestion, not the book gate
    monkeypatch.setattr(store_mod, "_default", s)
    app = FastAPI(); app.include_router(router)
    return TestClient(app), s, d


def up(c, cid, name, data):
    return c.post("/agents/client-profiling/meeting-notes", data={"client_id": cid}, files={"file": (name, data)})


_OK = lambda s, u: __import__('json').dumps({'in_scope': True, 'broad': False, 'answerable': True, 'answer': 'ok', 'groups': [], 'cites': ['C0']})  # noqa: E731


def test_pdf_upload_is_stored_and_readable_by_agent(client):
    c, s, d = client
    pdf = make_pdf("Meeting with Jane Fraser 2026-10-27. Jane now wants a 5 percent cap on equities.")
    r = up(c, "jfr", "2026-10-27-follow-up.pdf", pdf)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["clientId"] == "jfr" and n["date"] == "2026-10-27" and "5 percent cap" in n["originalText"]
    assert (d / "uploaded_meeting_notes.json").exists()
    assert any(x.id == n["id"] for x in s.get_notes("jfr"))
    assert DocumentStore(d).get_note("jfr", n["id"])  # survives restart
    res = handle_chat("What did we discuss in the last meeting?", "jfr", store=s, answer_chat=_OK)
    assert res.status == "ok" and n["id"] in str(res.data)  # newest note is the "last meeting"
    assert n["id"] in [x.id for x in res.sources]
    full = handle_chat(f"read {n['id']}", "jfr", store=s, answer_chat=_OK)
    assert "5 percent cap" in str(full.data)


def test_upload_isolated_to_client(client):
    c, s, _ = client
    up(c, "jfr", "a.txt", b"Jane Fraser confidential note about private matters here.")
    assert s.get_notes("ser") == [] and "confidential" not in str(c.get("/agents/client-profiling/meeting-notes/ser").json())
    assert len(c.get("/agents/client-profiling/meeting-notes/jfr").json()) == 3


def test_rejections_save_nothing(client):
    c, s, d = client
    assert up(c, "nobody", "a.txt", b"x" * 100).status_code == 403  # not in the book (unknown client)
    assert up(c, "jfr", "a.docx", b"x" * 100).status_code == 415
    assert up(c, "jfr", "empty.pdf", make_pdf("")).status_code == 422
    assert up(c, "jfr", "bad.pdf", b"not a pdf").status_code == 422
    assert not (d / "uploaded_meeting_notes.json").exists() and len(s.get_notes("jfr")) == 2
