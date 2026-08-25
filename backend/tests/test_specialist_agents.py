"""
Technical/Finance/General specialist nodes: the scope check that hands a
message back to triage when it doesn't belong here, and the tool-calling
decision the underlying LLM makes (search vs. direct answer) once in scope.
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import app.agents.nodes.finance as finance_module
import app.agents.nodes.general as general_module
import app.agents.nodes.technical as technical_module
from app.agents.nodes.finance import FinanceExpert
from app.agents.nodes.finance import ScopeCheck as FinanceScopeCheck
from app.agents.nodes.general import GeneralAssistant
from app.agents.nodes.general import ScopeCheck as GeneralScopeCheck
from app.agents.nodes.technical import ScopeCheck as TechnicalScopeCheck
from app.agents.nodes.technical import TechnicalSpecialist

from conftest import FakeLLM, run_async


# --- Technical --------------------------------------------------------

def _make_technical(monkeypatch, fake_llm):
    monkeypatch.setattr(technical_module, "get_groq_model", lambda: fake_llm)
    return TechnicalSpecialist()


def test_technical_out_of_scope_hands_back_to_triage(monkeypatch):
    fake_llm = FakeLLM(TechnicalScopeCheck(in_scope=False))
    agent = _make_technical(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what's a good ETF?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"
    assert result["next_agent"] == "triage"


def test_technical_in_scope_direct_answer_no_tool_call(monkeypatch):
    fake_llm = FakeLLM(
        TechnicalScopeCheck(in_scope=True),
        AIMessage(content="Use a list comprehension instead of the loop."),
    )
    agent = _make_technical(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="how do I speed up this loop?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "technical"
    assert result["technical_response"]["data"]["search_used"] is False
    assert not result["messages"][0].tool_calls


def test_technical_in_scope_emits_tool_call_when_llm_requests_search(monkeypatch):
    fake_llm = FakeLLM(
        TechnicalScopeCheck(in_scope=True),
        AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {"query": "python 3.13 release notes"}, "id": "c1"}]),
    )
    agent = _make_technical(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what's new in python 3.13?")]}

    result = run_async(agent.run(state))

    assert result["technical_response"]["data"]["search_used"] is True
    assert result["messages"][0].tool_calls[0]["name"] == "tavily_search"


def test_technical_resuming_after_tool_skips_scope_check(monkeypatch):
    # Only one response queued (the follow-up answer) - if the scope check
    # ran again it would starve the FakeLLM queue and raise.
    fake_llm = FakeLLM(AIMessage(content="Python 3.13 adds a JIT compiler."))
    agent = _make_technical(monkeypatch, fake_llm)
    state = {
        "messages": [
            HumanMessage(content="what's new in python 3.13?"),
            AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {}, "id": "c1"}]),
            ToolMessage(content="search results...", tool_call_id="c1"),
        ]
    }

    result = run_async(agent.run(state))

    assert result["technical_response"]["data"]["search_used"] is True
    assert result["messages"][0].content == "Python 3.13 adds a JIT compiler."


def test_technical_llm_failure_falls_back_gracefully(monkeypatch):
    fake_llm = FakeLLM(TechnicalScopeCheck(in_scope=True), RuntimeError("groq down"))
    agent = _make_technical(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="why is my build failing?")]}

    result = run_async(agent.run(state))

    assert "trouble processing" in result["messages"][0].content


# --- Finance ------------------------------------------------------------

def _make_finance(monkeypatch, fake_llm):
    monkeypatch.setattr(finance_module, "get_groq_model", lambda: fake_llm)
    return FinanceExpert()


def test_finance_out_of_scope_hands_back_to_triage(monkeypatch):
    fake_llm = FakeLLM(FinanceScopeCheck(in_scope=False))
    agent = _make_finance(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="how do I center a div?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"


def test_finance_expands_jargon_before_scope_check(monkeypatch):
    fake_llm = FakeLLM(
        FinanceScopeCheck(in_scope=True),
        AIMessage(content="A P/E ratio compares price to earnings."),
    )
    agent = _make_finance(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="what's a good p/e for a growth stock?")]}

    run_async(agent.run(state))

    scope_check_messages = fake_llm.calls[0]
    human_turn = next(m for m in scope_check_messages if m.type == "human")
    assert "price-to-earnings ratio" in human_turn.content


def test_finance_emits_action_tool_call_for_money_moving_request(monkeypatch):
    fake_llm = FakeLLM(
        FinanceScopeCheck(in_scope=True),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "propose_financial_action",
                "args": {"action_type": "transfer", "amount": 500, "description": "move $500 to savings"},
                "id": "c1",
            }],
        ),
    )
    agent = _make_finance(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="move $500 from checking to savings")]}

    result = run_async(agent.run(state))

    assert result["messages"][0].tool_calls[0]["name"] == "propose_financial_action"


def test_finance_response_carries_disclaimer(monkeypatch):
    fake_llm = FakeLLM(
        FinanceScopeCheck(in_scope=True),
        AIMessage(content="Diversification reduces risk."),
    )
    agent = _make_finance(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="how should I diversify?")]}

    result = run_async(agent.run(state))

    assert result["finance_response"]["data"]["disclaimer"]


# --- General --------------------------------------------------------------

def _make_general(monkeypatch, fake_llm):
    monkeypatch.setattr(general_module, "get_groq_model", lambda: fake_llm)
    return GeneralAssistant()


def test_general_hands_back_to_triage_when_topic_shifts_to_technical(monkeypatch):
    fake_llm = FakeLLM(GeneralScopeCheck(destination="technical"))
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="actually, why does my code throw a NullPointerException?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"
    assert result["next_agent"] == "triage"


def test_general_hands_back_to_triage_when_topic_shifts_to_finance(monkeypatch):
    fake_llm = FakeLLM(GeneralScopeCheck(destination="finance"))
    agent = _make_general(monkeypatch, fake_llm)
    state = {"messages": [HumanMessage(content="actually, should I invest in bonds?")]}

    result = run_async(agent.run(state))

    assert result["current_agent"] == "triage"


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
