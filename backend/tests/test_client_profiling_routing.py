"""Source routing (IS-78/79/80): notes vs IPS vs both vs ask. Fake chat fns, stubbed IPS answerer, JSON store, no network."""
import json
import time

import pytest

from app.agents.client_profiling import service
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore, StoreUnavailableError

Q = "What did we agree on risk?"


def router(source, conf=0.95):
    calls = []

    def chat(system, user):
        calls.append(user)
        return json.dumps({"source": source, "confidence": conf})
    chat.calls = calls
    return chat


def notes_chat(calls=None):
    def chat(system, user):
        if calls is not None:
            calls.append(1)
        return json.dumps({"in_scope": True, "broad": False, "answerable": True, "answer": "Moderate risk was agreed.",
                           "groups": [], "cites": ["C0"], "summary_request": False, "summary_format": "", "inference": ""})
    return chat


IPS_OK = {"status": "ok", "text": "Risk category: Balanced.", "sections": [],
          "sources": [{"type": "ips", "id": "jfr:v1", "client_id": "jfr", "version": 1, "label": "IPS v1"}]}


@pytest.fixture
def ips(monkeypatch):
    calls = []

    def stub(message, store, cid, chat):
        calls.append(cid)
        r = stub.result
        if isinstance(r, Exception):
            raise r
        return r
    stub.result, stub.calls = IPS_OK, calls
    monkeypatch.setattr(service, "_ips_answer", lambda m, s, c, ch: stub(m, s, c, ch))
    return stub


def blow(*a, **k):
    raise StoreUnavailableError("down")


def test_unclear_asks_which_source_without_data():
    r = handle_chat(Q, "jfr", router_chat=router("unclear"))
    assert r.tool == "clarify_source" and r.status == "needs_clarification"
    assert r.message == "Do you mean the meeting notes or the IPS?"
    assert [o["source"] for o in r.data["options"]] == ["notes", "ips", "both"]
    assert r.sources == [] and "answer" not in r.data


def test_confidence_threshold():
    assert handle_chat(Q, "jfr", router_chat=router("notes", 0.6)).tool == "clarify_source"
    r = handle_chat(Q, "jfr", router_chat=router("notes", 0.7), answer_chat=notes_chat())
    assert r.tool != "clarify_source" and r.data["routing"]["source"] == "notes"


def test_explicit_source_skips_router(ips):
    rc = router("unclear")
    r = handle_chat(Q, "jfr", source="ips", router_chat=rc)
    assert r.tool == "get_ips" and rc.calls == []


def test_ips_path_never_touches_notes(ips, monkeypatch):
    called = []
    monkeypatch.setattr(service, "answer_question", lambda *a, **k: called.append(1))
    r = handle_chat("What is the risk category in the IPS?", "jfr", router_chat=router("ips"))
    assert r.tool == "get_ips" and r.status == "ok" and r.message == "Risk category: Balanced."
    assert all(s.type == "ips" for s in r.sources) and r.data["routing"]["source"] == "ips" and called == []


def test_notes_path_never_calls_ips(ips):
    r = handle_chat("What did the client say about risk in meetings?", "jfr", router_chat=router("notes"), answer_chat=notes_chat())
    assert r.data["routing"]["source"] == "notes" and ips.calls == []
    assert all(s.type == "meeting_note" for s in r.sources)


def test_notes_db_down_no_ips_fallback(ips, monkeypatch):
    monkeypatch.setattr(service, "answer_question", blow)
    r = handle_chat("What did the client say?", "jfr", router_chat=router("notes"), answer_chat=notes_chat())
    assert r.tool == "source_unavailable"
    assert "meeting-notes database is unavailable" in r.message and "have not used the IPS" in r.message
    assert ips.calls == []


def test_ips_db_down_no_notes_fallback(ips, monkeypatch):
    ips.result = StoreUnavailableError("down")
    called = []
    monkeypatch.setattr(service, "answer_question", lambda *a, **k: called.append(1))
    r = handle_chat("What does the IPS say?", "jfr", router_chat=router("ips"))
    assert r.tool == "source_unavailable" and "IPS database is unavailable" in r.message and "not used the meeting notes" in r.message
    assert called == []


def test_no_ips_says_so_and_never_uses_notes(ips, monkeypatch):
    ips.result = {"status": "no_ips", "text": "", "sections": [], "sources": []}
    monkeypatch.setattr(service, "answer_question", blow)
    r = handle_chat("What does the IPS say?", "jfr", router_chat=router("ips"))
    assert r.tool == "get_ips" and r.status == "not_found" and r.message == "This client has no IPS yet." and r.sources == []


def test_both_labelled_blocks(ips):
    r = handle_chat("Compare the meeting notes with the IPS", "jfr", router_chat=router("both"), answer_chat=notes_chat())
    assert r.tool == "compare_sources"
    b = r.data["both"]
    assert b["notes"]["label"] == "Meeting notes" and b["ips"]["label"] == "IPS"
    assert b["notes"]["answer"]["text"] and b["ips"]["answer"]["text"] == IPS_OK["text"]
    assert {s.type for s in r.sources} <= {"ips", "meeting_note"}


def test_both_one_side_down_other_still_answers(ips, monkeypatch):
    ips.result = StoreUnavailableError("down")
    r = handle_chat("Compare", "jfr", source="both", answer_chat=notes_chat())
    b = r.data["both"]
    assert b["ips"]["answer"]["status"] == "unavailable" and "not used the meeting notes" in b["ips"]["answer"]["text"]
    assert b["notes"]["answer"]["text"] == "Moderate risk was agreed."
    ips.result = IPS_OK
    monkeypatch.setattr(service, "answer_question", blow)
    b = handle_chat("Compare", "jfr", source="both", answer_chat=notes_chat()).data["both"]
    assert b["notes"]["answer"]["status"] == "unavailable" and b["ips"]["answer"]["text"] == IPS_OK["text"]


def test_book_denial_before_routing(ips):
    rc = router("notes")
    r = handle_chat(Q, "jfr", book=["ser"], router_chat=rc, answer_chat=notes_chat())
    assert r.tool == "access_denied" and rc.calls == [] and ips.calls == []


def test_router_none_is_routing_unavailable(ips):
    def bad(s, u):
        return "not json"
    assert handle_chat(Q, "jfr", router_chat=bad).tool == "routing_unavailable"

    def down(s, u):
        raise ConnectionError("off")
    r = handle_chat(Q, "jfr", router_chat=down)
    assert r.tool == "routing_unavailable" and r.sources == [] and ips.calls == []


def test_out_of_scope_from_router(ips):
    r = handle_chat("What is the weather today?", "jfr", router_chat=router("out_of_scope"))
    assert r.tool == "out_of_scope" and ips.calls == []


def test_summary_skips_router_and_is_notes(ips):
    rc = router("ips")
    r = handle_chat("Summarise the meeting notes", "jfr", router_chat=rc, answer_chat=notes_chat())
    assert rc.calls == [] and r.data["routing"]["source"] == "notes"


def test_no_notes_returns_clear_message_quickly(ips, tmp_path):
    store = DocumentStore()
    store._notes = [n for n in store._notes if n.client_id != "jfr"]
    t = time.time()
    r = handle_chat("What did the client say about risk?", "jfr", store=store, router_chat=router("notes"), answer_chat=notes_chat())
    assert time.time() - t < 10
    assert r.status in ("not_found", "insufficient_information") and r.message and ips.calls == []


def test_question_for_client_with_no_notes_says_no_results_without_a_model_call():
    calls = []

    def chat(system, user):
        calls.append(1)
        return "{}"
    r = handle_chat("What did the client say about her cash reserve?", "ser", answer_chat=chat)  # seeded client without notes
    assert r.tool == "get_meeting_note" and r.status == "not_found" and r.message == "No meeting notes found." and calls == []


def test_client_lookup_store_down_is_source_specific_no_fallback(ips, monkeypatch):
    monkeypatch.setattr(service, "resolve_client", blow)
    r = handle_chat("What does the IPS say?", "jfr", source="ips")
    assert r.tool == "source_unavailable" and "IPS database is unavailable" in r.message and "not used the meeting notes" in r.message
    r = handle_chat("What did the client say?", "jfr", source="notes")
    assert r.tool == "source_unavailable" and "meeting-notes database is unavailable" in r.message and "not used the IPS" in r.message
    assert ips.calls == []


def test_ips_model_off_message_names_ips_and_never_uses_notes(ips, monkeypatch):
    ips.result = None
    monkeypatch.setattr(service, "answer_question", blow)
    r = handle_chat("What does the IPS say?", "jfr", router_chat=router("ips"))
    assert r.tool == "routing_unavailable" and "IPS" in r.message and "not used the meeting notes" in r.message and r.sources == []


def test_router_timeout_default_leaves_room_for_the_10s_no_results_bound():
    from app.agents.client_profiling import source_router
    assert "CLIENT_PROFILING_ROUTER_TIMEOUT_S\", \"5\"" in open(source_router.__file__).read()
