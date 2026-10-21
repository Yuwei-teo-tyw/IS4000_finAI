"""
TriageAgent routing decisions - the structured `RoutingDecision` output
drives handoff to market_researcher/general, a canned intro for 'meta'
questions, and a safe 'general' fallback if the routing call itself fails.
"""
from langchain_core.messages import HumanMessage

import app.agents.nodes.triage as triage_module
from app.agents.nodes.triage import RoutingDecision, TriageAgent

from conftest import FakeLLM, run_async


def _make_agent(monkeypatch, fake_llm):
    monkeypatch.setattr(triage_module, "get_groq_model", lambda: fake_llm)
    return TriageAgent()


def test_personal_finance_routes_to_general(monkeypatch):
    fake_llm = FakeLLM(RoutingDecision(destination="general"))
    agent = _make_agent(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="should I max out my 401k?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "general"
    assert result["next_agent"] == "general"


def test_routes_to_general(monkeypatch):
    fake_llm = FakeLLM(RoutingDecision(destination="general"))
    agent = _make_agent(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what's the weather like today?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "general"
    assert result["next_agent"] == "general"
    assert result["handoff_message"] is None


def test_meta_destination_returns_canned_introduction(monkeypatch):
    fake_llm = FakeLLM(RoutingDecision(destination="meta"))
    agent = _make_agent(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what can you help me with?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"
    assert result["next_agent"] is None
    assert result["skip_eval"] is True
    assert result["messages"][0].content == agent.get_agent_introduction()


def test_routing_error_falls_back_to_general(monkeypatch):
    fake_llm = FakeLLM(RuntimeError("groq is down"))
    agent = _make_agent(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="anything")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "general"
    assert result["next_agent"] == "general"


def test_routes_to_market_researcher(monkeypatch):
    fake_llm = FakeLLM(RoutingDecision(destination="market"))
    agent = _make_agent(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="are recession risks rising?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "market_researcher"
    assert result["next_agent"] == "market_researcher"
    assert "Market Researcher" in result["handoff_message"]
