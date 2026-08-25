"""
End-to-end tests through the real compiled graph (`build_graph`), backed by
an in-memory checkpointer instead of Postgres. Every LLM-backed node
(triage/technical/finance/general/eval) is monkeypatched to a `FakeLLM`
queued with the exact sequence of structured/tool-call responses that
scenario needs - everything else (pii_guard, routing, tool execution,
human_approval) runs for real.

`tavily_search` runs for real too, but with TAVILY_API_KEY deliberately
unset, so it returns a deterministic error string instead of making a
network call - the tool-calling loop only cares that the graph round-trips
through ToolNode and back, not what the search actually returned.

Together these four tests cover the graph's main regression surface: the
technical tool-calling loop, the finance compliance-driven regenerate
loop, the human-approval interrupt/resume loop, and PII redaction running
before any specialist ever sees the raw message.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import app.agents.nodes.context_manager as context_manager_module
import app.agents.nodes.eval_agent as eval_module
import app.agents.nodes.finance as finance_module
import app.agents.nodes.general as general_module
import app.agents.nodes.technical as technical_module
import app.agents.nodes.triage as triage_module
from app.agents.graph import build_graph
from app.agents.nodes.eval_agent import ComplianceCheck, EvalVerdict
from app.agents.nodes.finance import ScopeCheck as FinanceScopeCheck
from app.agents.nodes.general import ScopeCheck as GeneralScopeCheck
from app.agents.nodes.technical import ScopeCheck as TechnicalScopeCheck
from app.agents.nodes.triage import RoutingDecision

from conftest import FakeLLM, run_async


def _patch_all_llms(monkeypatch):
    """Give every LLM-backed node its own FakeLLM queue and return them
    keyed by node name, so each test fills in only the queues it needs."""
    fakes = {
        "triage": FakeLLM(),
        "technical": FakeLLM(),
        "finance": FakeLLM(),
        "general": FakeLLM(),
        "eval": FakeLLM(),
        # never queued in these short-conversation tests - context_manager
        # only calls the LLM once history is long enough to need compaction -
        # but it still needs a non-raising get_groq_model() to construct.
        "context_manager": FakeLLM(),
    }
    monkeypatch.setattr(triage_module, "get_groq_model", lambda: fakes["triage"])
    monkeypatch.setattr(technical_module, "get_groq_model", lambda: fakes["technical"])
    monkeypatch.setattr(finance_module, "get_groq_model", lambda: fakes["finance"])
    monkeypatch.setattr(general_module, "get_groq_model", lambda: fakes["general"])
    monkeypatch.setattr(eval_module, "get_groq_model", lambda: fakes["eval"])
    monkeypatch.setattr(context_manager_module, "get_groq_model", lambda: fakes["context_manager"])
    return fakes


def _graph():
    return build_graph(InMemorySaver())


def test_technical_tool_calling_loop_end_to_end(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="technical"))
    fakes["technical"].queue(
        TechnicalScopeCheck(in_scope=True),
        AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {"query": "python 3.13"}, "id": "c1"}]),
        AIMessage(content="Python 3.13 shipped a JIT compiler."),
    )
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""))

    app = _graph()
    config = {"configurable": {"thread_id": "tech-loop"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="what's new in python 3.13?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert final_ai.content == "Python 3.13 shipped a JIT compiler."
    assert result["technical_response"]["data"]["search_used"] is True
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert len(tool_messages) == 1
    assert "TAVILY_API_KEY" in tool_messages[0].content  # real tool ran, no key configured


def test_finance_compliance_regenerate_loop_end_to_end(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="finance"))
    fakes["finance"].queue(
        FinanceScopeCheck(in_scope=True),
        AIMessage(content="This fund guarantees a 20% return, no risk at all."),
        FinanceScopeCheck(in_scope=True),  # scope check re-runs on the regenerate pass
        AIMessage(content="Past performance doesn't guarantee future returns; diversify and consider your risk tolerance."),
    )
    fakes["eval"].queue(
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=False, severity="needs_rewrite", issue="unqualified guaranteed-return language"),
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=True, severity="none"),
    )

    app = _graph()
    config = {"configurable": {"thread_id": "finance-compliance"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="is this fund a sure thing?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert "no risk at all" not in final_ai.content.lower()
    assert "diversify" in final_ai.content.lower()
    # the non-compliant draft must not be visible anywhere in final history
    assert not any("no risk at all" in (m.content or "") for m in result["messages"])


def test_human_approval_interrupt_and_resume_end_to_end(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="finance"))
    fakes["finance"].queue(
        FinanceScopeCheck(in_scope=True),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "propose_financial_action",
                "args": {"action_type": "transfer", "amount": 500, "description": "move $500 to savings"},
                "id": "act-1",
            }],
        ),
        # resuming after the ToolMessage from human_approval - no second scope check
        AIMessage(content="Done - I've submitted the transfer for approval and it's been approved."),
    )
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""))

    app = _graph()
    config = {"configurable": {"thread_id": "human-approval"}}

    paused = run_async(app.ainvoke({"messages": [HumanMessage(content="move $500 to savings")]}, config=config))
    assert "__interrupt__" in paused
    assert paused["__interrupt__"][0].value["action"]["action_type"] == "transfer"

    resumed = run_async(app.ainvoke(Command(resume=True), config=config))

    final_ai = [m for m in resumed["messages"] if m.type == "ai" and m.content][-1]
    assert "approved" in final_ai.content.lower()
    tool_messages = [m for m in resumed["messages"] if m.type == "tool"]
    assert any("User approved" in m.content for m in tool_messages)


def test_pii_is_redacted_before_any_specialist_sees_it(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="general"))
    fakes["general"].queue(
        GeneralScopeCheck(destination="general"),
        AIMessage(content="I can't help verify SSNs, but I can answer general questions."),
    )
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""))

    app = _graph()
    config = {"configurable": {"thread_id": "pii-redaction"}}
    result = run_async(app.ainvoke(
        {"messages": [HumanMessage(content="is SSN 123-45-6789 formatted correctly?")]},
        config=config,
    ))

    assert result["pii_redacted"] is True
    human_messages = [m for m in result["messages"] if m.type == "human"]
    assert all("123-45-6789" not in (m.content or "") for m in human_messages)
    assert any("[REDACTED-SSN]" in (m.content or "") for m in human_messages)

    # confirm the specialist's own scope-check prompt never saw the raw SSN
    scope_check_call = fakes["general"].calls[0]
    assert not any("123-45-6789" in (m.content or "") for m in scope_check_call)
