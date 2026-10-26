"""Jira IS-73 (summarise meeting notes) / IS-74 (ask questions) acceptance-criteria gap tests.
Offline, deterministic: fake chat + in-memory stores. Live-model wording is NOT tested here, only the
prompt/validator wiring that enforces it."""
import json
import re

from app.agents.client_profiling import answer as answer_mod
from app.agents.client_profiling import summary as summary_mod
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc
from app.agents.client_profiling.summary import summarise_notes

EMPTY = {"cash_inflow": [], "cash_outflow": [], "risk_profile": [], "asset_class_preference": [], "cites": []}
BASE = {"in_scope": True, "broad": False, "summary_request": False, "answerable": True, "answer": "", "groups": [],
        "cites": [], "explanation": {}, "inference": ""}


class FakeStore:
    def __init__(self, notes):
        self.notes = notes

    def get_notes(self, cid):
        return list(self.notes)

    def get_client(self, cid):
        return None


def note(i, date, text):
    return MeetingNoteDoc(id=f"note_{i}", client_id="x", date=date, title=f"Meeting {i}", text=text)


def chat_of(**kw):
    return lambda s, u: json.dumps({**BASE, **kw})


# ------------------------------------------------------------------ IS-73
def test_is73_boundary_20000_words_chunks_cover_whole_note():
    words = [f"w{i}" for i in range(20000)]
    st = FakeStore([note(1, "2026-10-13", " ".join(words))])
    calls = []

    def chat(s, u):
        calls.append(u)
        return json.dumps(EMPTY)
    r = summarise_notes(st, "x", chat)
    assert r["coverage"]["truncated"] == []  # exactly at the limit: nothing uncovered, no warning
    assert len(calls) == 14  # ceil(20000/1500) chunk calls
    joined = "\n".join(calls)  # chunk calls run in parallel: order is not deterministic
    assert all(re.search(rf"\bw{i}\b", joined) for i in (0, 7499, 19999))  # first, middle and last word are all covered
    assert sum(f"(part {k} of 14)" in joined for k in range(1, 15)) == 14


def test_is73_over_limit_states_uncovered_part_and_drops_tail():
    words = [f"w{i}" for i in range(20001)]
    calls = []

    def chat(s, u):
        calls.append(u)
        return json.dumps(EMPTY)
    r = summarise_notes(FakeStore([note(1, "2026-10-13", " ".join(words))]), "x", chat)
    t = r["coverage"]["truncated"][0]
    assert t["covered_words"] == 20000 and t["total_words"] == 20001 and "20,001" in t["not_covered"]
    assert not any("w20000" in c for c in calls)


def test_is73_happy_bullets_under_four_headings_with_date_and_source():
    chat = lambda s, u: json.dumps({**EMPTY, "asset_class_preference": ["Keep 10% equities."], "cash_outflow": ["Cash S$30m needed."]})
    r = summarise_notes(FakeStore([note(1, "2026-10-13", "Keep 10% equities. Cash S$30m needed. Send IPS.")]), "x", chat)
    m = r["meetings"][0]
    assert m["date"] == "2026-10-13" and m["sources"][0]["date"] == "2026-10-13"
    assert [s["heading"] for s in m["sections"]] == ["Cash Inflow", "Cash Outflow", "Risk Profile", "Asset Class Preference"]
    assert [b["text"] for b in m["sections"][3]["bullets"]] == ["Keep 10% equities."]


def test_is73_profile_card_comes_first_in_payload():
    chat = lambda s, u: json.dumps(EMPTY)
    r = summarise_notes(DocumentStore(), "jfr", chat)
    keys = list(r)
    assert keys.index("profile_card") < keys.index("meetings")
    assert r["profile_card"]["title"] and r["profile_card"]["items"]


def test_is73_no_notes_end_to_end_no_invention(monkeypatch):
    class Empty(DocumentStore):
        def get_notes(self, cid):
            return []
    calls = []

    def chat(s, u):
        calls.append(u)
        return json.dumps({**BASE, "summary_request": True})
    r = handle_chat("summarise the meetings", "jfr", store=Empty(), answer_chat=chat)
    assert r.status == "not_found" and r.message == "No meeting notes found."
    assert "summary" not in r.data and not r.sources
    assert len(calls) == 0  # nothing to retrieve: no model call, nothing summarised


def test_is73_not_in_book_denied_nothing_retrieved_no_summary(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("summary must not run")
    monkeypatch.setattr(summary_mod, "summarise_notes", boom)
    calls = []
    r = handle_chat("summarise the meetings", "mlm", store=DocumentStore(), book=["jfr"],
                    answer_chat=lambda s, u: calls.append(u) or "{}")
    assert r.tool == "access_denied" and calls == [] and r.data == {} and r.sources == []


def test_is73_dates_latest_first():
    ns = [note(1, "2026-10-13", "Keep cash."), note(2, "2026-10-20", "Keep cash.")]
    r = summarise_notes(FakeStore(ns), "x", lambda s, u: json.dumps({**EMPTY, "risk_profile": ["Keep cash."]}))
    assert [m["date"] for m in r["covered_meetings"]] == ["2026-10-20", "2026-10-13"]
    assert [m["date"] for m in r["meetings"]] == ["2026-10-20", "2026-10-13"]
