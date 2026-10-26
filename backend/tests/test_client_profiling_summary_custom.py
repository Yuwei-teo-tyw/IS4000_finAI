"""User-steerable summary: a requested layout is followed, no request keeps the four default headings (fake chat)."""
import json

from app.agents.client_profiling import summary as summary_mod
from app.agents.client_profiling.answer import answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import MeetingNoteDoc, get_default_store
from app.agents.client_profiling.summary import CUSTOM_SYSTEM, SYSTEM, summarise_notes

TEXT = "Client has a bonus of 50000 each March. Monthly spending is 8000. Prefers equities."
BASE = {"in_scope": True, "broad": True, "summary_request": True, "summary_format": "", "answerable": True, "answer": "",
        "groups": [], "cites": [], "explanation": {"risk_category": "", "text": "", "recommended_asset_classes": [], "cites": []},
        "inference": ""}


class Store:
    def get_notes(self, cid):
        return [MeetingNoteDoc(id="note_1", client_id="x", date="2026-01-01", title="Review", text=TEXT)]

    def get_client(self, cid):
        return None


def recording(out):
    seen = []

    def chat(system, user):
        seen.append((system, user))
        return json.dumps(out)
    chat.seen = seen
    return chat


def test_default_has_no_adviser_request_and_four_headings():
    chat = recording({"cash_inflow": ["Bonus 50000 each March"], "cash_outflow": [], "risk_profile": [], "asset_class_preference": []})
    res = summarise_notes(Store(), "x", chat)
    assert chat.seen[0][0] == SYSTEM and "<adviser_request>" not in chat.seen[0][1]
    assert [s["heading"] for s in res["meetings"][0]["sections"]] == ["Cash Inflow", "Cash Outflow", "Risk Profile", "Asset Class Preference"]
    assert "custom_format" not in res


def test_custom_layout_is_followed_with_request_in_prompt():
    chat = recording({"sections": [{"heading": "Cash flow", "bullets": ["Bonus 50000 each March", "Spends 8000 monthly"]}]})
    res = summarise_notes(Store(), "x", chat, instruction="only cash flow, under one heading")
    assert chat.seen[0][0] == CUSTOM_SYSTEM and "only cash flow" in chat.seen[0][1]
    secs = res["meetings"][0]["sections"]
    assert [s["heading"] for s in secs] == ["Cash flow"] and len(secs[0]["bullets"]) == 2
    assert res["custom_format"] == "only cash flow, under one heading"


def test_custom_layout_still_drops_invented_figures_and_caps_sections():
    out = {"sections": [{"heading": f"H{i}", "bullets": ["Bonus 50000", "Invented 999999"]} for i in range(12)]}
    secs = summarise_notes(Store(), "x", recording(out), instruction="by topic")["meetings"][0]["sections"]
    assert len(secs) == 8
    assert [b["text"] for s in secs for b in s["bullets"]] == ["Bonus 50000"]  # invented figure dropped; repeats shown once


def test_custom_bad_model_output_gives_empty_sections_not_a_crash():
    res = summarise_notes(Store(), "x", lambda s, u: "not json", instruction="short")
    assert res["status"] == "ok" and res["meetings"][0]["sections"] == []


def test_router_passes_summary_format_through_and_cleans_it():
    st = get_default_store()
    prof = extract_key_facts(st, "jfr")
    a = answer_question("summarise as 3 bullets", st, prof, lambda s, u: json.dumps({**BASE, "summary_format": "  3 bullets  "}))
    assert a["summary_format"] == "3 bullets"
    a = answer_question("summarise", st, prof, lambda s, u: json.dumps({**BASE, "summary_format": "None"}))
    assert a["summary_format"] == ""


def test_service_uses_instruction_only_when_format_given(monkeypatch):
    calls = []

    def fake(store, cid, chat=None, **kw):
        calls.append(kw)
        return {"status": "ok", "message": "", "meetings": [], "covered_meetings": [], "coverage": {}}
    monkeypatch.setattr(summary_mod, "summarise_notes", fake)
    handle_chat("summarise as 3 bullets", "jfr", answer_chat=lambda s, u: json.dumps({**BASE, "summary_format": "3 bullets"}))
    handle_chat("summarise the notes", "jfr", answer_chat=lambda s, u: json.dumps(BASE))
    assert calls == [{"instruction": "3 bullets"}, {}]


def test_invented_format_for_a_bare_summary_request_is_dropped():
    st = get_default_store()
    prof = extract_key_facts(st, "jfr")
    invented = "The summary should cover the client's profile, goals, financial details and strategy."
    a = answer_question("Summarise the meeting notes", st, prof, lambda s, u: json.dumps({**BASE, "summary_format": invented}))
    assert a["summary_format"] == ""
    a = answer_question("Summarise the meetings as 3 bullets", st, prof, lambda s, u: json.dumps({**BASE, "summary_format": "3 bullets"}))
    assert a["summary_format"] == "3 bullets"


def test_same_fact_is_shown_once_across_meetings_but_changed_figures_are_kept():
    notes = [MeetingNoteDoc(id="note_2", client_id="x", date="2026-02-01", title="B", text="Very risk averse. Equities up to 15%."),
             MeetingNoteDoc(id="note_1", client_id="x", date="2026-01-01", title="A", text="Very risk averse. Equities up to 10%.")]

    class S:
        def get_notes(self, cid):
            return notes

        def get_client(self, cid):
            return None
    by_note = {"note_2": ["Very risk averse.", "Equities up to 15%."], "note_1": ["very risk averse", "Equities up to 10%."]}

    def chat(system, user):
        nid = "note_2" if "Meeting note note_2 " in user else "note_1"
        return json.dumps({"cash_inflow": [], "cash_outflow": [], "asset_class_preference": [], "risk_profile": by_note[nid]})
    res = summarise_notes(S(), "x", chat)
    texts = {m["note_id"]: [b["text"] for s in m["sections"] for b in s["bullets"]] for m in res["meetings"]}
    assert texts["note_2"] == ["Very risk averse.", "Equities up to 15%."]
    assert texts["note_1"] == ["Equities up to 10%."]


def test_summary_response_has_no_duplicate_key_facts_sections(monkeypatch):
    monkeypatch.setattr(summary_mod, "summarise_notes", lambda st, cid, chat=None, **k: {"status": "ok", "message": "", "meetings": [], "covered_meetings": [], "coverage": {}})
    r = handle_chat("summarise the notes", "jfr", answer_chat=lambda s, u: json.dumps(BASE))
    assert "sections" not in r.data and "summary" in r.data


def test_summary_is_one_merged_output_with_per_bullet_sources():
    notes = [MeetingNoteDoc(id="note_2", client_id="x", date="2026-02-01", title="B", text="Very risk averse. Equities up to 15%."),
             MeetingNoteDoc(id="note_1", client_id="x", date="2026-01-01", title="A", text="Very risk averse. Equities up to 10%.")]

    class S:
        def get_notes(self, cid):
            return notes

        def get_client(self, cid):
            return None

    def chat(system, user):
        nid = "note_2" if "Meeting note note_2 " in user else "note_1"
        eq = "Equities up to 15%." if nid == "note_2" else "Equities up to 10%."
        return json.dumps({"cash_inflow": [], "cash_outflow": [], "asset_class_preference": [eq], "risk_profile": ["Very risk averse."]})
    secs = {s["heading"]: s["bullets"] for s in summarise_notes(S(), "x", chat)["sections"]}
    assert [b["text"] for b in secs["Risk Profile"]] == ["Very risk averse."]
    assert {e["id"] for e in secs["Risk Profile"][0]["sources"]} == {"note_1", "note_2"}  # same fact, both meetings cited
    assert [b["text"] for b in secs["Asset Class Preference"]] == ["Equities up to 15%.", "Equities up to 10%."]  # changed figure kept


def test_bullets_that_only_restate_the_profile_card_are_absorbed():
    from app.agents.client_profiling.summary import _absorb_into_card
    card = {"title": "J", "items": [{"label": "Annual income", "value": "S$10.0m"}, {"label": "Monthly spending", "value": "S$150,000"},
                                    {"label": "Cash reserve", "value": "S$30.0m"}]}
    bullets = ["annual income of S$10m from salary and bonus", "S$150,000 a month on living costs.",
               "keep a cash reserve of S$30m so that she never has to sell investments to meet her expenses",
               "a fall of more than 10% would prompt her to sell"]
    secs = [{"heading": "X", "bullets": [{"text": t} for t in bullets]}]
    _absorb_into_card(card, secs)
    assert card["items"][0]["value"] == "S$10.0m (from salary and bonus)"  # qualifier merged into the card, not lost
    assert [b["text"] for b in secs[0]["bullets"]] == bullets[2:]  # substantive reasons and unrelated 10% are kept


def _two_meeting_store(old_text, new_text):
    notes = [MeetingNoteDoc(id="n2", client_id="x", date="2026-10-20", title="Follow-up", text=new_text),
             MeetingNoteDoc(id="n1", client_id="x", date="2026-10-13", title="First", text=old_text)]

    class S:
        def get_notes(self, cid):
            return notes

        def get_client(self, cid):
            return None
    return S()


def test_later_meeting_updates_a_value_the_earlier_one_stated():
    from app.agents.client_profiling.summary import _absorb_into_card, _mark_updates, _merge_meetings
    meetings = [
        {"note_id": "n2", "sources": [{"id": "n2", "date": "2026-10-20"}], "sections": [
            {"heading": "Cash Inflow", "bullets": [{"text": "Annual income is now S$12m from salary and bonus"}]},
            {"heading": "Asset Class Preference", "bullets": [{"text": "Open to up to 15% in blue-chip equities"}]}]},
        {"note_id": "n1", "sources": [{"id": "n1", "date": "2026-10-13"}], "sections": [
            {"heading": "Cash Inflow", "bullets": [{"text": "Annual income S$10m from salary and bonus"}]},
            {"heading": "Asset Class Preference", "bullets": [{"text": "Open to adding blue-chip equities, up to about 10%"}]}]}]
    secs = _merge_meetings(meetings)
    card = {"title": "J", "items": [{"label": "Annual income", "value": "S$12.0m"}]}
    _absorb_into_card(card, secs)
    _mark_updates(secs)
    assert "updated; was S$10m on 13 Oct 2026" in card["items"][0]["value"]  # card = latest value, previous one noted
    texts = {s["heading"]: [b["text"] for b in s["bullets"]] for s in secs}
    assert texts["Cash Inflow"] == []  # the stale S$10m is not listed as a current fact
    assert texts["Asset Class Preference"][0].startswith("Updated 20 Oct 2026:")
    assert texts["Asset Class Preference"][1].startswith("Earlier, 13 Oct 2026:")
