"""Summary routing safety net, model-down fallback and surfaced failures (fake chat, no network)."""
import json

from app.agents.client_profiling import summary as summary_mod
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import MeetingNoteDoc
from app.agents.client_profiling.summary import extractive_summary

TEXT = ("Client receives a bonus of 50000 each March. Monthly spending is 8000. "
        "Risk tolerance is balanced with a 10 year horizon. Prefers equities and bonds, avoids crypto.")
BASE = {"in_scope": True, "broad": True, "summary_request": False, "answerable": True, "answer": "", "groups": [],
        "cites": [], "explanation": {"risk_category": "", "text": "", "recommended_asset_classes": [], "cites": []},
        "inference": ""}


class Store:
    def __init__(self, notes):
        self.notes = notes

    def get_notes(self, cid):
        return list(self.notes)

    def get_client(self, cid):
        return None


def store():
    return Store([MeetingNoteDoc(id="note_1", client_id="jfr", date="2026-01-01", title="Review", text=TEXT)])


def chat_for(out):
    return lambda s, u: json.dumps(out)


def bullets(summary):
    return {sec["heading"]: [b["text"] for b in sec["bullets"]] for sec in summary["meetings"][0]["sections"]}


def test_extractive_fallback_is_verbatim_and_grouped():
    b = bullets(extractive_summary(store(), "jfr"))
    assert any("50000" in t for t in b["Cash Inflow"])
    assert any("8000" in t for t in b["Cash Outflow"])
    assert any("balanced" in t for t in b["Risk Profile"])
    assert any("equities" in t for t in b["Asset Class Preference"])
    assert extractive_summary(store(), "jfr")["degraded"] is True


def test_extractive_fallback_no_notes():
    assert extractive_summary(Store([]), "jfr")["status"] == "no_notes"


def test_model_down_summary_request_gets_labelled_fallback(monkeypatch):
    monkeypatch.setattr("app.agents.client_profiling.service.answer_question", lambda *a, **k: None)
    from app.agents.client_profiling import service
    r = handle_chat("Summarise the meeting notes", "jfr")
    assert r.status == "ok" and r.data["summary"]["degraded"] is True
    assert r.data["routing"]["method"] == "fallback" and "unavailable" in r.message


def test_model_down_non_summary_still_unavailable(monkeypatch):
    from app.agents.client_profiling import service
    monkeypatch.setattr(service, "answer_question", lambda *a, **k: None)
    assert handle_chat("what equities?", "jfr").tool == "routing_unavailable"


def test_summary_wording_overrides_false_model_flag(monkeypatch):
    from app.agents.client_profiling import service
    seen = {}
    monkeypatch.setattr(summary_mod, "summarise_notes", lambda st, cid, chat: seen.setdefault("called", True) and {"status": "ok", "meetings": []})
    handle_chat("Please summarise the notes", "jfr", answer_chat=chat_for(BASE))
    assert seen.get("called")


def test_summary_failure_is_surfaced_not_swallowed(monkeypatch):
    from app.agents.client_profiling import service

    def boom(*a, **k):
        raise RuntimeError("model timeout")
    monkeypatch.setattr(summary_mod, "summarise_notes", boom)
    r = handle_chat("Summarise the notes", "jfr", answer_chat=chat_for({**BASE, "summary_request": True}))
    assert "model timeout" in r.data["summary_error"]
    assert r.data["summary"]["degraded"] is True


def test_degraded_fallback_also_has_merged_sections():
    secs = {s["heading"]: s["bullets"] for s in extractive_summary(store(), "jfr")["sections"]}
    assert any("50000" in b["text"] for b in secs["Cash Inflow"]) and secs["Cash Inflow"][0]["sources"]
