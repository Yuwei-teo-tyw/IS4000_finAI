"""IS-74 combo: specific question + summary in one message (fake chat, no network)."""
import json

from app.agents.client_profiling import summary as summary_mod
from app.agents.client_profiling.service import handle_chat

_SUMM = {"status": "ok", "message": "", "profile_card": {}, "meetings": [{"note_id": "n", "date": "2026-10-13", "title": "t", "sections": [{"heading": "Risk Profile", "bullets": [{"text": "Keep cash."}]}], "sources": []}],
         "covered_meetings": [], "coverage": {}, "timings": {}}
_BASE = {"in_scope": True, "broad": True, "summary_request": True, "answerable": True, "answer": "", "groups": [], "cites": [],
         "explanation": {}, "inference": ""}


def _chat(**kw):
    return lambda s, u: json.dumps({**_BASE, **kw})


def _patch(monkeypatch, res):
    def fn(store, cid, chat=None):
        if isinstance(res, Exception):
            raise res
        return res
    monkeypatch.setattr(summary_mod, "summarise_notes", fn)


def test_combo_returns_answer_and_summary(monkeypatch):
    _patch(monkeypatch, _SUMM)
    r = handle_chat("what about equities, and summarise the meetings", "jfr", answer_chat=_chat(answer="She is open to up to 15% in equities.", cites=["N1"]))
    a = r.data["answer"]
    assert a["status"] == "ok" and "15%" in a["text"] and a["sources"] and a["summary_request"] is True and a["sections"] == []
    assert r.data["summary"]["meetings"][0]["sections"][0]["bullets"][0]["text"] == "Keep cash."
    assert "15%" in r.message


def test_pure_summary_has_empty_answer(monkeypatch):
    _patch(monkeypatch, _SUMM)
    r = handle_chat("summarise the meetings", "jfr", answer_chat=_chat())
    assert not r.data["answer"].get("text") and r.data["answer"]["sources"] == []
    assert "cannot find" not in json.dumps(r.data["answer"]).lower()
    assert r.data["summary"]["meetings"]


def test_unsupported_figure_dropped_but_summary_kept(monkeypatch):
    _patch(monkeypatch, _SUMM)
    r = handle_chat("equities and summarise", "jfr", answer_chat=_chat(answer="She wants 77% in equities.", cites=["N1"]))
    assert not r.data["answer"].get("text") and r.data["summary"]


def test_no_notes(monkeypatch):
    _patch(monkeypatch, {"status": "no_notes"})
    r = handle_chat("equities and summarise", "jfr", answer_chat=_chat(answer="Up to 15%.", cites=["N1"]))
    assert r.status == "not_found" and r.message == "No meeting notes found."


def test_summary_failure_keeps_answer(monkeypatch):
    _patch(monkeypatch, RuntimeError("down"))
    r = handle_chat("equities and summarise", "jfr", answer_chat=_chat(answer="She is open to up to 15% in equities.", cites=["N1"]))
    assert "15%" in r.data["answer"]["text"] and r.data["answer"]["sources"]
    assert r.data["summary_error"] == "RuntimeError: down" and r.data["summary"]["degraded"] is True  # surfaced, not swallowed


def test_specific_only_has_no_summary(monkeypatch):
    _patch(monkeypatch, _SUMM)
    r = handle_chat("equities?", "jfr", answer_chat=_chat(summary_request=False, broad=False, answer="Open to 15% equities.", cites=["N1"]))
    assert "summary" not in r.data and r.data["answer"]["summary_request"] is False
