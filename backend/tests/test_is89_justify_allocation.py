"""IS-89: justify an allocation choice from the meeting notes + strategy table (offline)."""
import json

from app.agents.client_profiling.alloc_dialogue import allocation_intent, justify_allocation
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc

NOTE = ("Jane is 45. She holds a long-term view of at least ten years and wants her portfolio to grow. "
        "She needs S$2m in cash over the next 2 years for expenses.")
ALLOC = {"buckets": [{"id": "liquidity", "strategy": "A"}, {"id": "longevity", "strategy": "E"}, {"id": "legacy", "strategy": "C"}]}


class St:
    def __init__(self, text=NOTE):
        self.notes = [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-01", title="First meeting", text=text)] if text else []

    def get_notes(self, cid):
        return self.notes


def test_justification_cites_note_and_table():
    chat = lambda s, u: json.dumps({"explanation": "The client has a long-term view and wants growth, which fits Strategy E."})  # noqa: E731
    r = justify_allocation(St(), "x", "Why did you pick E for Longevity?", ALLOC, chat)
    assert r["status"] == "ok" and "Strategy E (Growth)" in r["text"]
    assert 'Meeting note "First meeting" (2026-10-01)' in r["text"] and "long-term view" in r["text"]
    assert "Strategy table" in r["text"] and "expected return 5.0% p.a." in r["text"]
    assert r["sources"][0]["id"] == "n1" and r["applied"] is False


def test_invented_figure_in_model_text_dropped():
    chat = lambda s, u: json.dumps({"explanation": "The client will earn 77% with Strategy E."})  # noqa: E731
    r = justify_allocation(St(), "x", "Why did you pick E for Longevity?", ALLOC, chat)
    assert "77" not in r["text"] and "Meeting note" in r["text"]


def test_model_down_still_deterministic():
    def boom(s, u):
        raise RuntimeError
    r = justify_allocation(St(), "x", "Why did you pick E for Longevity?", ALLOC, boom)
    assert r["status"] == "ok" and "Meeting note" in r["text"]


def test_thin_notes_say_what_is_missing():
    r = justify_allocation(St("Met Jane for coffee."), "x", "Why did you pick E for Longevity?", ALLOC, None)
    assert r["status"] == "insufficient_information"
    assert "investment horizon" in r["text"] and "risk tolerance" in r["text"] and r["sources"] == []


def test_no_notes_at_all():
    r = justify_allocation(St(None), "x", "Why did you pick E for Longevity?", ALLOC, None)
    assert r["status"] == "insufficient_information" and "any meeting notes" in r["text"]


def test_no_allocation_offers_to_generate():
    r = justify_allocation(St(), "x", "Why did you pick E for Longevity?", None, None)
    assert r["status"] == "no_allocation" and "nothing to justify" in r["text"] and r["offer"]["action"] == "generate_allocation"


def test_intent_does_not_steal_guide_questions():
    assert allocation_intent("Why did you pick E for Longevity?") == "justify"
    assert allocation_intent("Why is the Liquidity portfolio only strategy A or B?") is None


def test_chat_routes_to_justify():
    r = handle_chat("Why did you pick E for Longevity?", client_id="jfr", store=DocumentStore(), allocation=None,
                    answer_chat=lambda s, u: "{}")
    assert r.tool == "allocation_dialogue" and r.data["allocation_dialogue"]["status"] in ("no_allocation", "ok", "insufficient_information")
