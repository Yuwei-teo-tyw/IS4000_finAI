"""
Pure routing-function tests for the graph edges in app/agents/graph.py -
`entry_router` and the four `route_after_*` functions. These take a state
dict and return a node name; no LLM involved, so they're tested directly
against hand-built state.
"""
from langchain_core.messages import AIMessage

from app.agents.graph import (
    entry_router,
    route_after_eval,
    route_after_general,
    route_after_market_researcher,
    route_after_triage,
)
from langgraph.graph import END


def _ai_with_tool_call(name: str, args=None, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


# --- entry_router -----------------------------------------------------

def test_entry_router_resumes_active_specialist():
    for agent in ("market_researcher", "general"):
        assert entry_router({"current_agent": agent}) == agent


def test_entry_router_defaults_to_triage():
    assert entry_router({"current_agent": None}) == "triage"
    assert entry_router({}) == "triage"


# --- route_after_triage -------------------------------------------------

def test_route_after_triage_follows_next_agent():
    for agent in ("market_researcher", "general"):
        assert route_after_triage({"next_agent": agent}) == agent


def test_route_after_triage_ends_on_canned_response():
    assert route_after_triage({"next_agent": None}) == END


# --- route_after_general ------------------------------------------------

def test_route_after_general_handoff_to_triage():
    state = {"next_agent": "triage", "messages": [AIMessage(content="out of scope")]}
    assert route_after_general(state) == "triage"


def test_route_after_general_tool_call_goes_to_tools():
    state = {"next_agent": None, "messages": [_ai_with_tool_call("tavily_search")]}
    assert route_after_general(state) == "general_tools"


def test_route_after_general_skip_eval_ends():
    state = {"next_agent": None, "messages": [AIMessage(content="canned")], "skip_eval": True}
    assert route_after_general(state) == END


def test_route_after_general_final_answer_goes_to_eval():
    state = {"next_agent": None, "messages": [AIMessage(content="the answer")], "skip_eval": False}
    assert route_after_general(state) == "eval"


# --- route_after_eval ---------------------------------------------------

def test_route_after_eval_regenerate_returns_to_producing_agent():
    for agent in ("market_researcher", "general", "triage"):
        state = {"eval_verdict": "regenerate", "current_agent": agent}
        assert route_after_eval(state) == agent


def test_route_after_eval_approve_or_flag_ends():
    assert route_after_eval({"eval_verdict": "approve", "current_agent": "general"}) == END
    assert route_after_eval({"eval_verdict": "flag", "current_agent": "general"}) == END


def test_route_after_eval_regenerate_with_unknown_agent_ends():
    assert route_after_eval({"eval_verdict": "regenerate", "current_agent": None}) == END


# --- route_after_market_researcher ------------------------------------

def test_route_after_market_researcher():
    assert route_after_market_researcher({"next_agent": "triage"}) == "triage"
    assert route_after_market_researcher({"next_agent": None, "skip_eval": False}) == "eval"
    assert route_after_market_researcher({"next_agent": None, "skip_eval": True}) == END
