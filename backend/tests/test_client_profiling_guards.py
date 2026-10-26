"""IS-73/IS-74 guards: empty / too-long questions and the 'not in my book' denial."""
import json

import pytest

from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore


class SpyStore(DocumentStore):
    def __init__(self):
        super().__init__()
        self.touched = 0

    def __getattribute__(self, name):
        if name in ("list_clients", "get_client", "get_notes", "get_ips_versions", "resolve_client"):
            object.__setattr__(self, "touched", object.__getattribute__(self, "touched") + 1)
        return object.__getattribute__(self, name)


class SpyChat:
    def __init__(self):
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        return json.dumps({"in_scope": True, "broad": False, "answerable": False, "answer": "", "groups": [], "cites": [],
                           "explanation": {"risk_category": "", "text": "", "recommended_asset_classes": [], "cites": []}})


@pytest.mark.parametrize("msg,expected", [
    ("", "Please enter a question."), ("   \n\t ", "Please enter a question."),
    ("x" * 1001, "Your question is over 1,000 characters. Please shorten or rephrase it."),
])
def test_invalid_questions_touch_nothing(msg, expected):
    store, chat = SpyStore(), SpyChat()
    store.touched = 0
    r = handle_chat(msg, "jfr", store=store, answer_chat=chat, book=["jfr"])
    assert (r.tool, r.status, r.message) == ("invalid_question", "needs_clarification", expected)
    assert chat.calls == 0 and store.touched == 0
    assert not r.data and not r.sources and not r.candidates


def test_exactly_1000_chars_passes_guard():
    r = handle_chat("a" * 1000, "jfr", store=DocumentStore(), answer_chat=SpyChat())
    assert r.tool != "invalid_question"


def test_denied_context_client_not_in_book():
    chat = SpyChat()
    r = handle_chat("What did he say about cash?", "mlm", store=DocumentStore(), answer_chat=chat, book=["jfr", "sha"])
    _assert_denied(r, chat)


def test_denied_named_client_while_context_is_other():
    chat = SpyChat()
    r = handle_chat("What did Marcus Lim say about property?", "jfr", store=DocumentStore(), answer_chat=chat, book=["jfr"])
    _assert_denied(r, chat)


def _assert_denied(r, chat):
    assert (r.tool, r.status) == ("access_denied", "insufficient_information")
    assert r.message == "I cannot access this client's meeting notes because they are not in your book."
    assert chat.calls == 0
    assert r.data == {} and r.sources == [] and r.candidates == []
    blob = r.model_dump_json().lower()
    assert "property" not in blob and "balanced approach" not in blob and "note_9001" not in blob


def test_allowed_client_in_book_works():
    chat = SpyChat()
    r = handle_chat("What is Jane's risk tolerance?", "jfr", store=DocumentStore(), answer_chat=chat, book=["jfr"])
    assert r.tool != "access_denied" and chat.calls == 1


def test_no_book_keeps_behaviour():
    chat = SpyChat()
    r = handle_chat("What did Marcus Lim say?", None, store=DocumentStore(), answer_chat=chat)
    assert r.tool != "access_denied" and r.client_id == "mlm"


def test_candidates_filtered_to_book():
    store = DocumentStore()
    r = handle_chat("Tell me about Zebediah Quux", None, store=store, answer_chat=SpyChat(), book=["jfr", "sha"])
    assert r.status in ("not_found", "needs_clarification")
    assert {c["id"] for c in r.candidates} <= {"jfr", "sha"}
    r2 = handle_chat("Tell me about Zebediah Quux", None, store=store, answer_chat=SpyChat())
    assert "mlm" in {c["id"] for c in r2.candidates}


def test_seed_has_mlm():
    store = DocumentStore()
    assert store.get_client("mlm").name == "Marcus Lim"
    assert [n.id for n in store.get_notes("mlm")] == ["note_9001"]


def test_http_book_validation_and_empty():
    from fastapi.testclient import TestClient
    from app.app import app
    c = TestClient(app)
    r = c.post("/agents/client-profiling/chat", json={"message": "  "})
    assert r.status_code == 200 and r.json()["tool"] == "invalid_question"
    assert c.post("/agents/client-profiling/chat", json={"message": "hi", "book": ["x"] * 201}).status_code == 422
