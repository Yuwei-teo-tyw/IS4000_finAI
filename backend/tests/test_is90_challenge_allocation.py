"""IS-90: challenge an allocation; propose, confirm before applying; rule limits; stance labels (offline)."""
import json

from app.agents.client_profiling.alloc_dialogue import challenge_allocation, handle_allocation_turn
from app.agents.client_profiling.store import MeetingNoteDoc

NOTE = ("Jane is 45. She holds a long-term view of at least ten years and says she wants more growth and can accept a fall of 30% in a bad year. "
        "She needs S$2m in cash over the next 2 years for expenses.")
CUR = {"buckets": [{"id": "liquidity", "strategy": "A"}, {"id": "longevity", "strategy": "C"}, {"id": "legacy", "strategy": "C"}]}


class St:
    def __init__(self, text=NOTE):
        self.notes = [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-01", title="Review", text=text)]

    def get_notes(self, cid):
        return self.notes

    def get_client(self, cid):
        return type("C", (), {"risk_category": "Balanced"})()


def fake(stance, answer, lon="C", cites=("N1",)):
    def chat(system, user):
        chat.calls.append(user)
        j = lambda t: f"The client {t}."  # noqa: E731
        return json.dumps({"stance": stance, "answer": answer, "cites": list(cites), "buckets": [
            {"id": "liquidity", "strategy": "A", "justification": j("needs cash soon")},
            {"id": "longevity", "strategy": lon, "justification": j("has a long horizon")},
            {"id": "legacy", "strategy": "C", "justification": j("wants a legacy")}]})
    chat.calls = []
    return chat


def strategies(r):
    return {b["id"]: b["strategy"] for b in r["allocation"]["buckets"]}


def test_agrees_proposes_but_does_not_apply():
    r = challenge_allocation(St(), "x", "The client wants more growth in Longevity", [], CUR, chat=fake("agree", "The notes show she wants more growth.", lon="E"))
    assert r["stanceLabel"] == "Agrees" and r["text"].startswith("Agrees.")
    assert r["applied"] is False and strategies(r)["longevity"] == "C"
    assert r["proposal"]["changes"] == ["longevity"] and "not applied yet" in r["text"] and "confirm" in r["text"]
    assert r["sources"] and r["sources"][0]["id"] == "n1"


def test_confirm_applies_only_then():
    r1 = challenge_allocation(St(), "x", "The client wants more growth in Longevity", [], CUR, chat=fake("agree", "The notes show she wants more growth.", lon="E"))
    r2 = challenge_allocation(St(), "x", "yes, confirm", [], CUR, pending=r1["proposal"], chat=None)
    assert r2["applied"] is True and strategies(r2)["longevity"] == "E" and "Applied" in r2["text"]
    assert strategies(r2)["liquidity"] == "A"


def test_confirm_via_history_proposal():
    r1 = challenge_allocation(St(), "x", "The client wants more growth in Longevity", [], CUR, chat=fake("agree", "Notes support it.", lon="D"))
    hist = [{"role": "assistant", "text": r1["text"], "proposal": r1["proposal"]}]
    r2 = challenge_allocation(St(), "x", "ok go ahead", hist, CUR)
    assert r2["applied"] is True and strategies(r2)["longevity"] == "D"


def test_reject_keeps_current():
    r = challenge_allocation(St(), "x", "no", [], CUR, pending={"buckets": [{"id": "longevity", "strategy": "E"}]})
    assert r["applied"] is False and strategies(r)["longevity"] == "C"


def test_disagrees_shows_notes_and_changes_nothing():
    r = challenge_allocation(St(), "x", "Client wants more growth in Longevity", [], CUR, chat=fake("disagree", "Current strategy already fits the horizon."))
    assert r["stanceLabel"] == "Disagrees" and r["proposal"] is None and r["applied"] is False
    assert "What the notes say" in r["text"] and strategies(r)["longevity"] == "C"


def test_agree_without_note_support_downgraded():
    r = challenge_allocation(St("Met for coffee."), "x", "Client wants more growth in Longevity", [], CUR,
                             chat=fake("agree", "Sure.", lon="E", cites=()))
    assert r["stanceLabel"] == "Disagrees" and r["proposal"] is None


def test_partly_agrees_label():
    r = challenge_allocation(St(), "x", "Client wants more growth in Longevity", [], CUR, chat=fake("partial", "Notes support a smaller step.", lon="D"))
    assert r["stanceLabel"] == "Partly agrees" and r["proposal"]["changes"] == ["longevity"]


def test_liquidity_above_b_refused_without_model():
    c = fake("agree", "should not be called", lon="E")
    r = challenge_allocation(St(), "x", "Client wants more growth in Liquidity, use strategy E", [], CUR, chat=c)
    assert c.calls == [] and r["stanceLabel"] == "Disagrees" and r["proposal"] is None
    assert "limited to Strategy A" in r["text"] and "Longevity" in r["text"] and strategies(r)["liquidity"] == "A"


def test_liquidity_blocked_even_if_model_proposes_it():
    def chat(s, u):
        return json.dumps({"stance": "agree", "answer": "Fine.", "cites": ["N1"], "buckets": [
            {"id": "liquidity", "strategy": "F", "justification": "The client likes it."},
            {"id": "longevity", "strategy": "C", "justification": "The client is fine."},
            {"id": "legacy", "strategy": "C", "justification": "The client is fine."}]})
    r = challenge_allocation(St(), "x", "Client wants a bit more return on the cash side, liquidity too conservative", [], CUR, chat=chat)
    assert strategies(r)["liquidity"] == "A" and r["proposal"] is None


def test_second_pushback_sees_earlier_turns():
    c = fake("disagree", "Still no.")
    hist = [{"role": "user", "text": "Client wants more growth in Longevity"}, {"role": "assistant", "text": "Disagrees. Current fits."}]
    r = challenge_allocation(St(), "x", "He insists, still wants more", hist, CUR, chat=c)
    assert "Client wants more growth in Longevity" in c.calls[0] and "Disagrees. Current fits." in c.calls[0]
    assert r["stanceLabel"] == "Disagrees"


def test_no_allocation_nothing_to_change():
    r = challenge_allocation(St(), "x", "Client wants more growth in Longevity", [], None, chat=fake("agree", "x"))
    assert r["status"] == "no_allocation" and r["offer"]["action"] == "generate_allocation"


def test_model_unavailable_unchanged():
    def boom(s, u):
        raise RuntimeError
    r = challenge_allocation(St(), "x", "Client wants more growth in Longevity", [], CUR, chat=lambda s, u: "bad")
    assert r["status"] == "unavailable" and r["applied"] is False and strategies(r)["longevity"] == "C"


def test_non_allocation_turn_ignored():
    assert handle_allocation_turn(St(), "x", "What is the weather?", [], CUR) is None
