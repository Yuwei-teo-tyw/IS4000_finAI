"""
Graph wiring for the Client Profiling specialist: triage routing, the
missing-client guard, and the node's ToolResult -> Markdown conversion.
No network, no real LLM, no DB: routing uses a FakeLLM and `handle_chat`
is monkeypatched where the node imports it.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

import app.agents.nodes.client_profiling as cp_module
import app.agents.nodes.context_manager as context_manager_module
import app.agents.nodes.eval_agent as eval_module
import app.agents.nodes.general as general_module
import app.agents.nodes.market_researcher as market_researcher_module
import app.agents.nodes.triage as triage_module
from app.agents.client_profiling.schemas import SourceRef, ToolResult
from app.agents.graph import (
    AGENT_DISPLAY_NAMES, SPECIALISTS, build_graph, entry_router,
    route_after_client_profiling, route_after_triage,
)
from app.agents.nodes.client_profiling import ClientProfilingNode
from app.agents.nodes.triage import RoutingDecision, TriageAgent

from conftest import FakeLLM, run_async


def _triage(monkeypatch, destination):
    fake = FakeLLM(RoutingDecision(destination=destination))
    monkeypatch.setattr(triage_module, "get_groq_model", lambda: fake)
    return TriageAgent()


def _stub_handle_chat(monkeypatch, result):
    calls = []

    def fake(message, client_id=None, **kw):
        calls.append({"message": message, "client_id": client_id, **kw})
        return result

    monkeypatch.setattr(cp_module, "handle_chat", fake)
    return calls


def _state(client_id="C001", text="summarise the meetings"):
    return {"messages": [HumanMessage(content=text)], "client_id": client_id}


# --- registration / edges -------------------------------------------------

def test_registered_as_specialist():
    assert "client_profiling" in SPECIALISTS
    assert AGENT_DISPLAY_NAMES["client_profiling"] == "Client Profiling Agent"
    assert route_after_triage({"next_agent": "client_profiling"}) == "client_profiling"


def test_entry_router_retriages_client_profiling():
    assert entry_router({"current_agent": "client_profiling"}) == "triage"
    assert entry_router({"current_agent": "general"}) == "general"


def test_route_after_client_profiling():
    assert route_after_client_profiling({"next_agent": "general"}) == "general"
    assert route_after_client_profiling({"next_agent": None}) == END


# --- triage ---------------------------------------------------------------

def test_triage_routes_to_client_profiling_with_client(monkeypatch):
    agent = _triage(monkeypatch, "client_profiling")
    result = run_async(agent.run(_state()))
    assert result["next_agent"] == "client_profiling"
    assert result["current_agent"] == "client_profiling"
    assert result["scope_checked"] is True


def test_triage_guard_without_client_id(monkeypatch):
    for cid in (None, ""):
        agent = _triage(monkeypatch, "client_profiling")
        result = run_async(agent.run(_state(client_id=cid)))
        assert result["next_agent"] is None
        assert result["skip_eval"] is True
        assert "select or open a client" in result["messages"][0].content


def test_triage_market_and_general_unchanged_with_client(monkeypatch):
    assert run_async(_triage(monkeypatch, "market").run(_state()))["next_agent"] == "market_researcher"
    assert run_async(_triage(monkeypatch, "general").run(_state()))["next_agent"] == "general"


# --- node -----------------------------------------------------------------

def test_node_renders_sections_summary_and_book(monkeypatch):
    summary = {"degraded": True, "notice": "Model unavailable: extractive summary.",
               "sections": [{"heading": "Cash reserve", "bullets": [{"text": "Keeps 6 months."}, "Plain bullet"]}],
               "meetings": [{"sections": [{"heading": "IGNORED", "bullets": []}]}]}
    calls = _stub_handle_chat(monkeypatch, ToolResult(tool="get_meeting_note", client_id="C001", data={"summary": summary}))
    out = run_async(ClientProfilingNode().run(_state()))
    text = out["messages"][0].content
    assert "Model unavailable" in text and "### Cash reserve" in text
    assert "- Keeps 6 months." in text and "- Plain bullet" in text and "IGNORED" not in text
    assert "**" not in text
    assert calls == [{"message": "summarise the meetings", "client_id": "C001", "book": ["C001"]}]
    assert out["current_agent"] == "client_profiling" and out["next_agent"] is None
    assert out["skip_eval"] is True and out["conversation_ended"] is False


def test_node_renders_meetings_when_no_sections(monkeypatch):
    summary = {"meetings": [{"date": "2026-03-18", "title": "Review",
                             "sections": [{"heading": "Goals", "bullets": [{"text": "Retire at 60"}]}]}]}
    _stub_handle_chat(monkeypatch, ToolResult(tool="get_meeting_note", data={"summary": summary}))
    text = run_async(ClientProfilingNode().run(_state()))["messages"][0].content
    assert "### 2026-03-18 - Review" in text and "### Goals" in text and "- Retire at 60" in text


def test_node_renders_answer_with_sources(monkeypatch):
    ref = SourceRef(type="meeting_note", id="note_1", client_id="C001", date="2026-03-18").model_dump(mode="json")
    ref2 = SourceRef(type="meeting_note", id="note_2", client_id="C001", date="2026-04-02").model_dump(mode="json")
    _stub_handle_chat(monkeypatch, ToolResult(tool="get_meeting_note", data={
        "answer": {"status": "ok", "text": "He wants a 6-month cash reserve.", "sources": [ref, ref2, ref]}}))
    text = run_async(ClientProfilingNode().run(_state()))["messages"][0].content
    assert text.startswith("He wants a 6-month cash reserve.")
    assert text.endswith("Sources: 2026-03-18, 2026-04-02")


def test_node_out_of_scope_falls_back_to_general(monkeypatch):
    _stub_handle_chat(monkeypatch, ToolResult(tool="out_of_scope", status="insufficient_information",
                                              message="I can't answer that question.",
                                              data={"answer": {"text": "refusal"}}))
    out = run_async(ClientProfilingNode().run(_state(text="what's the weather")))
    assert out["next_agent"] == "general" and out["scope_checked"] is True
    assert "messages" not in out
    assert route_after_client_profiling(out) == "general"


def test_node_access_denied_not_found_unavailable(monkeypatch):
    cases = [
        ToolResult(tool="access_denied", status="insufficient_information", message="I cannot access this client's meeting notes because they are not in your book."),
        ToolResult(tool="get_meeting_note", status="not_found", message="No meeting notes found."),
        ToolResult(tool="routing_unavailable", status="insufficient_information", message="The local model is unavailable, so this question was not routed."),
    ]
    for r in cases:
        _stub_handle_chat(monkeypatch, r)
        out = run_async(ClientProfilingNode().run(_state()))
        assert out["messages"][0].content == r.message
        assert out["next_agent"] is None and out["skip_eval"] is True


def test_node_without_client_id_never_calls_service(monkeypatch):
    calls = _stub_handle_chat(monkeypatch, ToolResult(tool="x"))
    out = run_async(ClientProfilingNode().run(_state(client_id=None)))
    assert calls == [] and "select or open a client" in out["messages"][0].content


def test_node_handle_chat_exception_is_contained(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cp_module, "handle_chat", boom)
    out = run_async(ClientProfilingNode().run(_state()))
    assert "try again" in out["messages"][0].content


# --- end to end through the compiled graph --------------------------------

def test_graph_end_to_end_routes_to_client_profiling(monkeypatch):
    fakes = {k: FakeLLM() for k in ("triage", "general", "market", "eval", "ctx")}
    monkeypatch.setattr(triage_module, "get_groq_model", lambda: fakes["triage"])
    monkeypatch.setattr(general_module, "get_groq_model", lambda: fakes["general"])
    monkeypatch.setattr(market_researcher_module, "get_groq_model", lambda: fakes["market"])
    monkeypatch.setattr(eval_module, "get_groq_model", lambda: fakes["eval"])
    monkeypatch.setattr(context_manager_module, "get_groq_model", lambda: fakes["ctx"])
    calls = _stub_handle_chat(monkeypatch, ToolResult(tool="get_meeting_note", data={
        "answer": {"status": "ok", "text": "Moderate risk.", "sources": []}}))
    fakes["triage"].queue(RoutingDecision(destination="client_profiling"))

    app = build_graph(InMemorySaver())
    result = run_async(app.ainvoke(
        {"messages": [HumanMessage(content="what is his risk attitude?")], "client_id": "C007"},
        config={"configurable": {"thread_id": "cp-e2e"}}))

    assert result["messages"][-1].content == "Moderate risk."
    assert result["current_agent"] == "client_profiling"
    assert calls[0]["book"] == ["C007"]
    assert fakes["eval"].calls == []  # skip_eval: no eval LLM call


# --- IS-78/79/80: source clarification, compare, labels, IPS triage --------

from app.agents.nodes.client_profiling import parse_source_choice  # noqa: E402

CLARIFY = ToolResult(tool="clarify_source", status="needs_clarification", client_id="C001",
                     message="Do you mean the meeting notes or the IPS?",
                     data={"options": [{"source": "notes", "label": "Meeting notes"}, {"source": "ips", "label": "IPS"},
                                       {"source": "both", "label": "Both"}]})


def test_parse_source_choice():
    assert parse_source_choice("the IPS") == "ips"
    assert parse_source_choice("Meeting notes") == "notes"
    assert parse_source_choice("both") == "both"
    assert parse_source_choice("meeting notes and the IPS") == "both"
    assert parse_source_choice("what is the weather in Singapore today please tell me") is None
    assert parse_source_choice("") is None


def test_node_clarify_lists_options_and_sets_pending(monkeypatch):
    _stub_handle_chat(monkeypatch, CLARIFY)
    out = run_async(ClientProfilingNode().run(_state(text="What did we agree on risk?")))
    text = out["messages"][0].content
    assert "Meeting notes, IPS, Both" in text and out["pending_source_question"] == "What did we agree on risk?"
    assert out["skip_eval"] is True


def test_node_reply_resumes_original_question_with_chosen_source(monkeypatch):
    calls = _stub_handle_chat(monkeypatch, ToolResult(tool="get_ips", data={"answer": {"status": "ok", "text": "Balanced.", "sources": [
        SourceRef(type="ips", id="C001:v1", client_id="C001", version=1, label="IPS v1").model_dump(mode="json")]}}))
    state = {**_state(text="the IPS"), "pending_source_question": "What did we agree on risk?"}
    out = run_async(ClientProfilingNode().run(state))
    assert calls == [{"message": "What did we agree on risk?", "client_id": "C001", "book": ["C001"], "source": "ips"}]
    assert out["messages"][0].content == "Balanced.\n\nSources: IPS v1" and out["pending_source_question"] is None


def test_node_non_choice_reply_is_a_new_question(monkeypatch):
    calls = _stub_handle_chat(monkeypatch, ToolResult(tool="get_meeting_note", message="x"))
    state = {**_state(text="What is his cash reserve?"), "pending_source_question": "What did we agree on risk?"}
    run_async(ClientProfilingNode().run(state))
    assert calls[0]["message"] == "What is his cash reserve?" and "source" not in calls[0]


def test_node_compare_renders_labelled_blocks(monkeypatch):
    note = SourceRef(type="meeting_note", id="n1", client_id="C001", date="2026-03-18").model_dump(mode="json")
    ips = SourceRef(type="ips", id="C001:v2", client_id="C001", version=2, label="IPS v2").model_dump(mode="json")
    _stub_handle_chat(monkeypatch, ToolResult(tool="compare_sources", data={"both": {
        "notes": {"label": "Meeting notes", "answer": {"text": "Wants lower risk.", "sources": [note]}},
        "ips": {"label": "IPS", "answer": {"text": "Risk category: Balanced.", "sources": [ips]}}}}))
    text = run_async(ClientProfilingNode().run(_state(text="Compare the meeting notes with the IPS")))["messages"][0].content
    assert "### Meeting notes\n\nWants lower risk.\nSource (Meeting notes): 2026-03-18" in text
    assert "### IPS\n\nRisk category: Balanced.\nSource (IPS): IPS v2" in text


def test_entry_router_resumes_client_profiling_only_on_source_pick():
    base = {"current_agent": "client_profiling", "pending_source_question": "q"}
    assert entry_router({**base, "messages": [HumanMessage(content="IPS")]}) == "client_profiling"
    assert entry_router({**base, "messages": [HumanMessage(content="what is inflation")]}) == "triage"
    assert entry_router({"current_agent": "client_profiling", "messages": [HumanMessage(content="IPS")]}) == "triage"


def test_triage_ips_question_goes_to_client_profiling(monkeypatch):
    out = run_async(_triage(monkeypatch, "client_profiling").run({**_state(text="What does the IPS say about liquidity?")}))
    assert out["next_agent"] == "client_profiling"
    out = run_async(_triage(monkeypatch, "client_profiling").run({**_state(client_id=None, text="What does the IPS say?")}))
    assert "meeting notes or IPS" in out["messages"][0].content


def test_triage_prompts_mention_ips():
    from app.prompts.prompt_builder import get_prompt
    assert "IPS" in get_prompt("triage.routing_system") and "IPS" in get_prompt("triage.introduction")
