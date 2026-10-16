"""
Finance/General specialist nodes: the scope check that hands a
message back to triage when it doesn't belong here, and the tool-calling
decision the underlying LLM makes (search vs. direct answer) once in scope.
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import app.agents.nodes.finance as finance_module
import app.agents.nodes.general as general_module
from app.agents.nodes.finance import FinanceExpert
from app.agents.nodes.finance import ScopeCheck as FinanceScopeCheck
from app.agents.nodes.general import GeneralAssistant
from app.agents.nodes.general import ScopeCheck as GeneralScopeCheck

from conftest import FakeLLM, run_async


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
