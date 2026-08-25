"""
Pure routing-function tests for the graph edges in app/agents/graph.py -
`entry_router` and the five `route_after_*` functions. These take a state
dict and return a node name; no LLM involved, so they're tested directly
against hand-built state.
"""
from langchain_core.messages import AIMessage

from app.agents.graph import (
    entry_router,
    route_after_eval,
    route_after_finance,
    route_after_general,
    route_after_technical,
    route_after_triage,
)
from langgraph.graph import END


def _ai_with_tool_call(name: str, args=None, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


# --- entry_router -----------------------------------------------------

def test_entry_router_resumes_active_specialist():
    for agent in ("technical", "finance", "general"):
        assert entry_router({"current_agent": agent}) == agent


def test_entry_router_defaults_to_triage():
    assert entry_router({"current_agent": None}) == "triage"
    assert entry_router({}) == "triage"


# --- route_after_triage -------------------------------------------------

def test_route_after_triage_follows_next_agent():
    for agent in ("technical", "finance", "general"):
        assert route_after_triage({"next_agent": agent}) == agent


def test_route_after_triage_ends_on_canned_response():
    assert route_after_triage({"next_agent": None}) == END


# --- route_after_technical / route_after_general (same shape) ---------

def test_route_after_technical_handoff_to_triage():
    state = {"next_agent": "triage", "messages": [AIMessage(content="out of scope")]}
    assert route_after_technical(state) == "triage"


def test_route_after_technical_tool_call_goes_to_tools():
    state = {"next_agent": None, "messages": [_ai_with_tool_call("tavily_search")]}
    assert route_after_technical(state) == "technical_tools"


def test_route_after_technical_skip_eval_ends():
    state = {"next_agent": None, "messages": [AIMessage(content="canned")], "skip_eval": True}
    assert route_after_technical(state) == END


def test_route_after_technical_final_answer_goes_to_eval():
    state = {"next_agent": None, "messages": [AIMessage(content="the answer")], "skip_eval": False}
    assert route_after_technical(state) == "eval"


def test_route_after_general_mirrors_technical():
    handoff = {"next_agent": "triage", "messages": [AIMessage(content="x")]}
    assert route_after_general(handoff) == "triage"

    tools = {"next_agent": None, "messages": [_ai_with_tool_call("tavily_search")]}
    assert route_after_general(tools) == "general_tools"

    final = {"next_agent": None, "messages": [AIMessage(content="answer")], "skip_eval": False}
    assert route_after_general(final) == "eval"


# --- route_after_finance (has the extra human-approval branch) --------

def test_route_after_finance_handoff_to_triage():
    state = {"next_agent": "triage", "messages": [AIMessage(content="out of scope")]}
    assert route_after_finance(state) == "triage"


def test_route_after_finance_action_call_goes_to_human_approval():
    state = {
        "next_agent": None,
        "messages": [_ai_with_tool_call("propose_financial_action", {"action_type": "buy"})],
    }
    assert route_after_finance(state) == "human_approval"


def test_route_after_finance_search_call_goes_to_finance_tools():
    state = {"next_agent": None, "messages": [_ai_with_tool_call("tavily_search")]}
    assert route_after_finance(state) == "finance_tools"


def test_route_after_finance_skip_eval_ends():
    state = {"next_agent": None, "messages": [AIMessage(content="canned")], "skip_eval": True}
    assert route_after_finance(state) == END


def test_route_after_finance_final_answer_goes_to_eval():
    state = {"next_agent": None, "messages": [AIMessage(content="the answer")], "skip_eval": False}
    assert route_after_finance(state) == "eval"


# --- route_after_eval ---------------------------------------------------

def test_route_after_eval_regenerate_returns_to_producing_agent():
    for agent in ("technical", "finance", "general", "triage"):
        state = {"eval_verdict": "regenerate", "current_agent": agent}
        assert route_after_eval(state) == agent


def test_route_after_eval_approve_or_flag_ends():
    assert route_after_eval({"eval_verdict": "approve", "current_agent": "finance"}) == END
    assert route_after_eval({"eval_verdict": "flag", "current_agent": "finance"}) == END


def test_route_after_eval_regenerate_with_unknown_agent_ends():
    assert route_after_eval({"eval_verdict": "regenerate", "current_agent": None}) == END
