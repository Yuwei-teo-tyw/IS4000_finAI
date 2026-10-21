"""
General specialist node: the scope check that hands a message back to
triage when it belongs with the Market Researcher, and the tool-calling
decision the underlying LLM makes (search vs. direct answer) once in scope.
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import app.agents.nodes.general as general_module
from app.agents.nodes.general import GeneralAssistant
from app.agents.nodes.general import ScopeCheck as GeneralScopeCheck

from conftest import FakeLLM, run_async


def _make_general(monkeypatch, fake_llm):
    monkeypatch.setattr(general_module, "get_groq_model", lambda: fake_llm)
    return GeneralAssistant()


def test_general_hands_back_to_triage_when_topic_shifts_to_market(monkeypatch):
    fake_llm = FakeLLM(GeneralScopeCheck(destination="market"))
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="actually, are recession risks rising right now?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"


def test_general_answers_personal_finance_questions(monkeypatch):
    fake_llm = FakeLLM(
        GeneralScopeCheck(destination="general"),
        AIMessage(content="A P/E ratio compares a share price to earnings per share."),
    )
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what's a P/E ratio?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "general"
    assert "P/E" in result["messages"][0].content


def test_general_answers_when_in_scope(monkeypatch):
    fake_llm = FakeLLM(
        GeneralScopeCheck(destination="general"),
        AIMessage(content="The Eiffel Tower is in Paris."),
    )
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="where's the Eiffel Tower?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "general"
    assert result["messages"][0].content == "The Eiffel Tower is in Paris."


def test_general_resuming_after_tool_skips_scope_check(monkeypatch):
    fake_llm = FakeLLM(AIMessage(content="It's sunny and 72F today."))
    agent = _make_general(monkeypatch, fake_llm)
    state = {
        "messages": [
            HumanMessage(content="what's the weather today?"),
            AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {}, "id": "c1"}]),
            ToolMessage(content="weather data...", tool_call_id="c1"),
        ]
    }

    result = run_async(agent.run(state))

    assert result["messages"][0].content == "It's sunny and 72F today."


def test_general_skips_scope_check_once_routing_is_settled(monkeypatch):
    fake_llm = FakeLLM(AIMessage(content="Hello!"))
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="hi")], "scope_checked": True}

    result = run_async(agent.run(state))

    assert len(fake_llm.calls) == 1  # answer only, no scope check
    assert result["current_agent"] == "general"


def test_scope_check_sees_the_workspace_context(monkeypatch):
    fake_llm = FakeLLM(GeneralScopeCheck(destination="general"), AIMessage(content="ok"))
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="is this suitable for her?")], "client_context": "CTX: Mei Tan"}

    run_async(agent.run(state))

    assert any("Mei Tan" in m.content for m in fake_llm.calls[0])
