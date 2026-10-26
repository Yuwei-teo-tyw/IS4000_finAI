"""End-to-end through the HTTP endpoint; also proves the existing triage/graph are not involved."""
import json
import pathlib

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)
URL = "/agents/client-profiling/chat"


def reply(**kw):
    out = {"in_scope": True, "broad": False, "answerable": True, "answer": "", "groups": [], "cites": []}
    out.update(kw)
    return out


OK_CHAT = lambda s, u: json.dumps(reply(answer="Fine.", cites=["C0"]))  # noqa: E731


@pytest.fixture(autouse=True)
def _router(fake_router):
    pass


@pytest.fixture(autouse=True)
def _all_in_book():
    """These tests exercise the endpoint, not the book gate: put every seeded client in the (JSON) book."""
    from app.agents.client_profiling.store import get_default_store
    s = get_default_store()
    for c in s.list_clients():
        s.set_in_book(c.id, True)


def ask(message, client_id="ser", **kw):
    r = client.post(URL, json={"message": message, "client_id": client_id, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_notes_question_uses_get_meeting_note():
    r = ask("What did we discuss during the last meeting?", client_id="jfr")
    assert r["tool"] == "get_meeting_note" and r["data"]["routing"]["scope"] == "notes"


def test_explicit_note_id_reads_that_note():
    r = ask("What does note_1013 say?", client_id="jfr")
    assert r["tool"] in ("read_meeting_note", "get_meeting_note")


def test_ambiguous_client_returns_no_data():
    r = ask("Compare Sergio and David's notes", client_id=None)
    assert r["status"] == "needs_clarification" and r["data"] == {} and r["sources"] == []
    r = ask("Show notes for client Michael Brown")
    assert r["status"] in ("needs_clarification", "not_found") and r["data"] == {}


def test_no_client_context_never_defaults():
    r = ask("Show me the notes", client_id=None)
    assert r["status"] != "ok" and r["data"] == {}


def test_isolation_across_clients():
    names = {"ser": "Ermotti", "dso": "Solomon", "jfr": "Fraser", "teo": "Teo", "sha": "Shane"}
    for cid in names:
        blob = json.dumps(ask("Summarise the meeting notes", client_id=cid))
        for other, n in names.items():
            if other != cid and n != "Teo":
                assert n not in blob


def test_triage_routes_to_client_profiling():
    # changed by decision: triage now has a client_profiling destination (it was deliberately untouched before)
    src = (pathlib.Path(__file__).parent.parent / "app/agents/nodes/triage.py").read_text()
    assert "client_profiling" in src


def test_bad_or_down_model_gives_routing_unavailable_without_data():
    from app.agents.client_profiling.service import handle_chat as hc
    assert hc("hi", "jfr", answer_chat=lambda s, u: "rm -rf /").tool == "routing_unavailable"

    def down(s, u):
        raise ConnectionError("local model not running")
    r = hc("hi", "jfr", answer_chat=down)
    assert r.tool == "routing_unavailable" and r.data["routing"]["method"] == "unavailable" and not r.sources


def test_routing_method_reported_for_ui():
    from app.agents.client_profiling.service import handle_chat as hc
    r = hc("q", "jfr", answer_chat=OK_CHAT)
    assert r.data["routing"]["method"] == "local_llm"


def test_service_has_no_removed_tools_or_keyword_routing():
    import inspect
    from app.agents.client_profiling import service, llm
    src = inspect.getsource(service) + inspect.getsource(llm)
    for w in ("_tool_for", "score_risk", "propose_3L", "map_SAA", "select_route", "_scope_sections"):
        assert w not in src


def test_single_model_call_for_a_normal_question():
    from app.agents.client_profiling.service import handle_chat as hc
    calls = []

    def chat(s, u):
        calls.append(u)
        return OK_CHAT(s, u)
    hc("What is her annual income?", "jfr", answer_chat=chat)
    assert len(calls) == 1


def test_message_blank_on_refusal_and_first_sentence_on_ok():
    from app.agents.client_profiling.service import handle_chat
    no = lambda s, u: json.dumps(reply(answerable=False))  # noqa: E731
    r = handle_chat("q", "jfr", answer_chat=no)
    assert r.data["answer"]["status"] == "cannot_answer" and r.message == ""
    ok = lambda s, u: json.dumps(reply(answer="The client is Jane Fraser. More.", cites=["C0"]))  # noqa: E731
    r = handle_chat("who is the current client?", "jfr", answer_chat=ok)
    assert r.data["answer"]["status"] == "ok" and r.message == "The client is Jane Fraser."
