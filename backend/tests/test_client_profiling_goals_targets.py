"""Regression: 'what are her life goals' must surface quantified targets/ages/horizons from a note.

Root cause was the answer prompt (one short sentence, specific-fact mode), not retrieval or validation.
"""
import json
import os

import pytest

from app.agents.client_profiling import answer as ans_mod
from app.agents.client_profiling.answer import answer_question, build_context
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.store import MeetingNoteDoc

LINE = "She is currently 45 years old, and wants her investment portfolio to hit 700M within 8 years"
TEXT = ("First meeting with Jane Fraser. Her priorities are keeping her capital safe and steady income. "
        "She prefers cash and government bonds.\n\n" + LINE)


class Store:
    def get_notes(self, cid):
        return [MeetingNoteDoc(id="note_1", client_id="x", date="2026-10-13", title="First meeting", text=TEXT)]

    def get_client(self, cid):
        from types import SimpleNamespace
        return SimpleNamespace(id=cid, name="Jane Fraser")


def _ask(answer, cites=("N1",), q="what are her life goals"):
    seen = {}

    def chat(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"in_scope": True, "broad": False, "answerable": True, "answer": answer, "groups": [],
                           "cites": list(cites), "explanation": {"risk_category": "", "text": "", "recommended_asset_classes": [], "cites": []},
                           "summary_request": False, "summary_format": "", "inference": ""})
    st = Store()
    return answer_question(q, st, extract_key_facts(st, "x"), chat), seen


def test_goal_chunk_reaches_prompt():
    st = Store()
    ctx, _ = build_context(st, extract_key_facts(st, "x"), {}, "what are her life goals")
    assert "700M within 8 years" in ctx and "45 years old" in ctx


def test_prompt_tells_model_to_list_all_goals_with_targets():
    _, seen = _ask("x")
    assert "GOALS:" in seen["system"] and "quantified target" in seen["system"]
    assert "700M within 8 years" in seen["user"]


def test_validator_keeps_grounded_figures():
    res, _ = _ask("Capital safe and steady income; hit 700M within 8 years; currently 45 years old.")
    assert res["status"] == "ok"
    assert "700M" in res["text"] and "8 years" in res["text"] and "45" in res["text"]


def test_validator_still_drops_invented_figures():
    res, _ = _ask("Hit 900M within 8 years.")
    assert res["status"] == "cannot_answer"


def test_backstop_adds_targets_when_model_lists_only_priorities():
    res, _ = _ask("Her priorities are keeping her capital safe and steady income.")
    assert res["status"] == "ok"
    assert "700M within 8 years" in res["text"] and "45 years old" in res["text"]
    assert any("700M" in (x.get("passage") or "") for x in res["sources"])


def test_backstop_not_triggered_for_non_goal_question():
    res, _ = _ask("Her priorities are keeping her capital safe and steady income.", q="which bonds does she like")
    assert "700M" not in res["text"]


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("RUN_LIVE_PROFILING_TESTS"), reason="set RUN_LIVE_PROFILING_TESTS=1 (needs the local model)")
def test_live_life_goals_mentions_target_and_horizon():
    from app.agents.client_profiling.llm import local_chat_json
    st = Store()  # fresh in-memory store holding only the seeded sentence
    res = answer_question("what are her life goals", st, extract_key_facts(st, "x"), local_chat_json)
    assert res and res["status"] == "ok"
    text = res["text"] + " " + " ".join(l["text"] for s in res["sections"] for l in s["lines"])
    assert "700M" in text and "8 years" in text
