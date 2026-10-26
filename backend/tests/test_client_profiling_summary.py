"""IS-73 summary + IS-74 Q&A additions (fake chat, no network)."""
import json
import threading

from app.agents.client_profiling.answer import CANNOT, NOT_ENOUGH
from app.agents.client_profiling.answer import answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc, get_default_store
from app.agents.client_profiling.summary import summarise_notes


class FakeStore:
    def __init__(self, notes):
        self.notes = notes

    def get_notes(self, cid):
        return list(self.notes)

    def get_client(self, cid):
        return None


def note(i, date, text, cid="x"):
    return MeetingNoteDoc(id=f"note_{i}", client_id=cid, date=date, title=f"Meeting {i}", text=text)


def fake(out):
    calls = []

    def chat(system, user):
        calls.append(user)
        return json.dumps(out(user) if callable(out) else out)
    chat.calls = calls
    return chat


E = {"cash_inflow": [], "cash_outflow": [], "risk_profile": [], "asset_class_preference": [], "cites": []}
H = ["Cash Inflow", "Cash Outflow", "Risk Profile", "Asset Class Preference"]


def per_note_chat(by_note):
    calls = []

    def chat(system, user):
        calls.append(user)
        for nid, out in by_note.items():
            if f"Meeting note {nid} " in user:
                return json.dumps({**E, **out})
        return json.dumps(E)
    chat.calls = calls
    return chat


def bullets(m, heading):
    return [b["text"] for s in m["sections"] if s["heading"] == heading for b in s["bullets"]]


TWO = [note(1, "2026-10-13", "Equities about 10% and S$30m cash."), note(2, "2026-10-20", "Equities up to 15%. Cash S$30m needed. Salary S$5m.")]
BY = {"note_1": {"asset_class_preference": ["Equities limit about 10%."], "cash_outflow": ["Cash S$30m reserve."]},
      "note_2": {"asset_class_preference": ["Equities limit up to 15%."], "cash_inflow": ["Salary S$5m."]}}


def test_four_headings_in_order_latest_first_no_merge_no_action_items():
    chat = per_note_chat(BY)
    r = summarise_notes(FakeStore(TWO), "x", chat)
    assert r["status"] == "ok" and [m["date"] for m in r["meetings"]] == ["2026-10-20", "2026-10-13"]
    for m in r["meetings"]:
        assert [s["heading"] for s in m["sections"]] == H
        assert set(m) == {"note_id", "date", "title", "sections", "sources"}
    assert bullets(r["meetings"][0], "Cash Inflow") == ["Salary S$5m."]
    assert bullets(r["meetings"][0], "Asset Class Preference") == ["Equities limit up to 15%."]
    assert bullets(r["meetings"][1], "Cash Outflow") == ["Cash S$30m reserve."]
    assert bullets(r["meetings"][1], "Risk Profile") == []
    assert "overview" not in r and "action_items" not in json.dumps(r) and "key_decisions" not in json.dumps(r)
    assert [m["date"] for m in r["covered_meetings"]] == ["2026-10-20", "2026-10-13"]
    assert r["coverage"] == {"total_notes": 2, "truncated": []}
    assert len(chat.calls) == 2  # one per note, no merge call


def test_single_note_dedupes_and_has_sources():
    chat = per_note_chat({"note_1": {"risk_profile": ["Keep cash.", "keep cash"]}})
    r = summarise_notes(FakeStore([note(1, "2026-10-13", "Met Jane.")]), "x", chat)
    assert len(chat.calls) == 1
    assert bullets(r["meetings"][0], "Risk Profile") == ["Keep cash."] and r["meetings"][0]["sources"][0]["id"] == "note_1"


def test_cap_per_heading():
    many = {"risk_profile": [f"Concern {n} two." for n in "abcdefgh"]}
    r = summarise_notes(FakeStore([note(1, "2026-10-13", "x")]), "x", per_note_chat({"note_1": many}))
    assert len(bullets(r["meetings"][0], "Risk Profile")) == 6


def test_no_notes_no_model_call():
    chat = fake({})
    r = summarise_notes(FakeStore([]), "x", chat)
    assert r["status"] == "no_notes" and r["message"] == "No meeting notes found." and r["covered_meetings"] == [] and chat.calls == []
    assert r["meetings"] == [] and "overview" not in r


def test_long_note_map_reduce_covers_whole_note():
    words = [f"w{i}" for i in range(4000)]
    for pos, tag in ((10, "alpha"), (1700, "beta"), (3900, "gamma")):
        words[pos] = tag
    st = FakeStore([note(1, "2026-10-13", " ".join(words))])

    def out(user):
        return {**E, "risk_profile": [t for t in ("alpha", "beta", "gamma") if t in user]}
    chat = fake(out)
    r = summarise_notes(st, "x", chat)
    assert len(chat.calls) == 3  # 1500 + 1500 + 1000
    assert sorted(bullets(r["meetings"][0], "Risk Profile")) == ["alpha", "beta", "gamma"]


def test_over_limit_reports_truncated_range():
    st = FakeStore([note(1, "2026-10-13", " ".join(["w"] * 23400))])
    chat = fake(E)
    r = summarise_notes(st, "x", chat)
    assert r["coverage"]["truncated"] == [{"note_id": "note_1", "covered_words": 20000, "total_words": 23400,
                                           "not_covered": "words 20,001-23,400 were not covered"}]
    assert len(chat.calls) == 14  # ceil(20000 / 1500)
    assert "words 20001" not in chat.calls[-1]


def test_unsupported_figure_bullet_dropped():
    st = FakeStore([note(1, "2026-10-13", "Client wants 10% equities and S$30m cash.")])
    r = summarise_notes(st, "x", fake({**E, "asset_class_preference": ["Equities 10%.", "Equities 25%."], "cash_outflow": ["Cash S$30m."],
                                       "cash_inflow": ["Call back in 99 days."]}))
    m = r["meetings"][0]
    assert bullets(m, "Asset Class Preference") == ["Equities 10%."] and bullets(m, "Cash Outflow") == ["Cash S$30m."] and bullets(m, "Cash Inflow") == []


def test_profile_card_deterministic_no_model():
    st = get_default_store()
    chat = fake(E)
    a, b = summarise_notes(st, "jfr", chat), summarise_notes(st, "jfr", chat)
    assert a["profile_card"] == b["profile_card"]
    items = {i["label"]: i["value"] for i in a["profile_card"]["items"]}
    assert a["profile_card"]["title"] == "Jane Fraser"
    assert items["Annual income"] == "S$10.0m" and items["Managed assets"] == "S$500.0m" and items["Monthly spending"] == "S$150,000"


def test_summary_request_flag_path_is_cheap():
    out = {"in_scope": True, "broad": True, "summary_request": True, "answerable": True, "answer": "", "groups": [], "cites": [],
           "explanation": {}, "inference": ""}
    st = get_default_store()
    prof = extract_key_facts(st, "jfr")
    a = answer_question("summarise her meetings", st, prof, lambda s, u: json.dumps(out))
    assert a["summary_request"] is True and a["text"] == "" and a["sections"] == []
    a = answer_question("q", st, prof, lambda s, u: json.dumps({**out, "summary_request": False, "broad": False, "answer": "Open to 15% equities.", "cites": ["N1"]}))
    assert a["summary_request"] is False and a["status"] == "ok"


def _qa(**kw):
    out = {"in_scope": True, "broad": False, "summary_request": False, "answerable": True, "answer": "", "cites": [], "inference": ""}
    out.update(kw)
    st = get_default_store()
    return answer_question("q", st, extract_key_facts(st, "jfr"), lambda s, u: json.dumps(out))


def test_inference_validated():
    a = _qa(answerable=False, inference="Inference (not stated in the notes): she may prefer low-volatility bonds.")
    assert a["status"] == "cannot_answer" and a["text"] == NOT_ENOUGH and a["inference"].startswith("Inference")
    assert _qa(answerable=False, inference="She would accept 77% in equities.")["inference"] == ""
    assert _qa(answerable=False)["inference"] == "" and _qa(answerable=False)["text"] == CANNOT
    assert _qa(answerable=False, inference="she likes bonds")["inference"].startswith("Inference (not stated in the notes):")


def test_two_date_conflict_answer_passes():
    txt = "Equities 10% on 13 Oct 2026, 15% on 20 Oct 2026 (latest)."
    a = _qa(answer=txt, cites=["N1", "N2"])
    assert a["status"] == "ok" and "13 Oct" in a["text"] and "latest" in a["text"]
    assert {s["id"] for s in a["sources"]} == {"note_1020", "note_1013"}
