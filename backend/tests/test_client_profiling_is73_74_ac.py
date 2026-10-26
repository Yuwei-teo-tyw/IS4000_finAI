"""IS-73 / IS-74 acceptance-criteria gap tests: not-enough-information + labelled inference, chat rendering of the
profile card, per-bullet meeting dates, question + summary together. Offline (fake chat)."""
import json

from langchain_core.messages import HumanMessage

import app.agents.nodes.client_profiling as cp_module
from app.agents.client_profiling import answer as answer_mod
from app.agents.client_profiling.answer import NOT_ENOUGH, answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.schemas import SourceRef, ToolResult
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import get_default_store
from app.agents.nodes.client_profiling import ClientProfilingNode, render_tool_result

from conftest import run_async

BASE = {"in_scope": True, "broad": False, "summary_request": False, "answerable": False, "answer": "", "groups": [],
        "cites": [], "explanation": {}, "inference": ""}


def test_is74_nothing_answers_gives_not_enough_info_then_labelled_inference():
    inf = "Inference (not stated in the notes): she may favour low-volatility bonds."
    r = handle_chat("What colour is her car?", "jfr", answer_chat=lambda s, u: json.dumps({**BASE, "inference": inf}))
    a = r.data["answer"]
    assert a["status"] == "cannot_answer" and a["text"] == NOT_ENOUGH == "There is not enough information in the meeting notes to answer this."
    assert a["inference"] == {"label": "Inference (not from the notes)", "text": inf} and a["sources"] == []
    md = render_tool_result(r)  # the multi-agent chat shows the sentence, then the clearly labelled inference
    assert md.startswith(NOT_ENOUGH) and md.endswith(inf)


def test_is74_no_inference_when_none_can_be_given_just_cannot_find():
    r = handle_chat("What colour is her car?", "jfr", answer_chat=lambda s, u: json.dumps(BASE))
    assert r.data["answer"]["text"] == answer_mod.CANNOT and "inference" not in r.data["answer"]
    assert "Inference" not in render_tool_result(r)


def test_is74_conflict_rule_is_in_prompt_and_both_dated_answers_cite_both_notes():
    assert "latest meeting" in answer_mod.SYSTEM and "EVERY meeting" in answer_mod.SYSTEM
    st = get_default_store()
    out = {**BASE, "answerable": True, "cites": ["N1", "N2"],
           "answer": "On 13 Oct 2026 about 10%; on 20 Oct 2026 (latest meeting) up to 15%."}
    a = answer_question("equities?", st, extract_key_facts(st, "jfr"), lambda s, u: json.dumps(out))
    assert a["status"] == "ok" and len(a["sources"]) == 2 and all(s["date"] and s["id"] for s in a["sources"])


def test_is74_answer_sources_carry_note_id_and_date_for_the_link():
    ref = SourceRef(type="meeting_note", id="note_1", client_id="C001", date="2026-03-18").model_dump(mode="json")
    md = render_tool_result(ToolResult(tool="get_meeting_note", data={"answer": {"status": "ok", "text": "Six months.", "sources": [ref]}}))
    assert md == "Six months.\n\nSources: 2026-03-18"


def _summary_result(answer_text=""):
    src = {"id": "n1", "date": "2026-10-13"}
    summary = {"status": "ok", "profile_card": {"title": "J", "items": [{"label": "Annual income", "value": "S$12.0m (updated; was S$10m on 13 Oct 2026)"}]},
               "sections": [{"heading": "Risk Profile", "bullets": [{"text": "Very risk averse.", "sources": [src, {"id": "n2", "date": "2026-10-20"}]}]}]}
    ans = {"status": "ok", "text": answer_text, "sources": [{**src, "type": "meeting_note", "client_id": "C001"}] if answer_text else []}
    return ToolResult(tool="get_meeting_note", data={"summary": summary, "answer": ans})


def test_is73_chat_markdown_has_card_first_and_each_bullet_cites_its_meeting_dates():
    md = render_tool_result(_summary_result())
    assert md.index("Annual income: S$12.0m (updated; was S$10m on 13 Oct 2026)") < md.index("### Risk Profile")
    assert "- Very risk averse. (meeting 2026-10-13, 2026-10-20)" in md


def test_is74_question_plus_summary_renders_answer_then_summary():
    md = render_tool_result(_summary_result("She is open to 15% equities."))
    assert md.startswith("She is open to 15% equities.") and md.index("Sources: 2026-10-13") < md.index("### Risk Profile")


def test_is74_node_no_client_open_asks_to_open_one(monkeypatch):
    called = []
    monkeypatch.setattr(cp_module, "handle_chat", lambda *a, **k: called.append(1))
    out = run_async(ClientProfilingNode().run({"messages": [HumanMessage(content="summarise the notes")], "client_id": ""}))
    assert not called and "open a client first" in out["messages"][0].content
