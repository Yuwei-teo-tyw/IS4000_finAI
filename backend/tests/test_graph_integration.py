"""
End-to-end tests through the real compiled graph (`build_graph`), backed by
an in-memory checkpointer instead of Postgres. Every LLM-backed node
(triage/general/market_researcher/eval) is monkeypatched to a `FakeLLM`
queued with the exact sequence of structured/tool-call responses that
scenario needs - everything else (pii_guard, routing, tool execution)
runs for real.

`tavily_search` runs for real too, but with TAVILY_API_KEY deliberately
unset, so it returns a deterministic error string instead of making a
network call - the tool-calling loop only cares that the graph round-trips
through ToolNode and back, not what the search actually returned.

Together these tests cover the graph's main regression surface: the
general assistant's tool-calling loop, the compliance-driven regenerate
loop, PII redaction running before any specialist ever sees the raw
message, and a specialist handoff settling in one hop.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.agents.nodes.context_manager as context_manager_module
import app.agents.nodes.eval_agent as eval_module
import app.agents.nodes.general as general_module
import app.agents.nodes.market_researcher as market_researcher_module
import app.agents.nodes.triage as triage_module
from app.agents.graph import build_graph
from app.agents.nodes.eval_agent import ComplianceCheck, EvalVerdict
from app.agents.nodes.market_researcher import MarketScope
from app.agents.nodes.triage import RoutingDecision

from conftest import FakeLLM, run_async


def _patch_all_llms(monkeypatch):
    """Give every LLM-backed node its own FakeLLM queue and return them
    keyed by node name, so each test fills in only the queues it needs."""
    fakes = {
        "triage": FakeLLM(),
        "general": FakeLLM(),
        "market_researcher": FakeLLM(),
        "eval": FakeLLM(),
        # never queued in these short-conversation tests - context_manager
        # only calls the LLM once history is long enough to need compaction -
        # but it still needs a non-raising get_groq_model() to construct.
        "context_manager": FakeLLM(),
    }
    monkeypatch.setattr(triage_module, "get_groq_model", lambda: fakes["triage"])
    monkeypatch.setattr(general_module, "get_groq_model", lambda: fakes["general"])
    monkeypatch.setattr(market_researcher_module, "get_groq_model", lambda: fakes["market_researcher"])
    monkeypatch.setattr(eval_module, "get_groq_model", lambda: fakes["eval"])
    monkeypatch.setattr(context_manager_module, "get_groq_model", lambda: fakes["context_manager"])
    return fakes


def _graph():
    return build_graph(InMemorySaver())


def test_general_tool_calling_loop_end_to_end(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="general"))
    fakes["general"].queue(  # triage just routed here - no scope check
        AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {"query": "python 3.13"}, "id": "c1"}]),
        AIMessage(content="Python 3.13 shipped a JIT compiler."),
    )
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""), ComplianceCheck(compliant=True, severity="none"))

    app = _graph()
    config = {"configurable": {"thread_id": "general-tool-loop"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="what's new in python 3.13?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert final_ai.content == "Python 3.13 shipped a JIT compiler."
    assert result["current_agent"] == "general"
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert len(tool_messages) == 1
    assert "TAVILY_API_KEY" in tool_messages[0].content  # real tool ran, no key configured


def test_compliance_regenerate_loop_end_to_end(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="general"))
    fakes["general"].queue(  # triage just routed here - no scope check
        AIMessage(content="This fund guarantees a 20% return, no risk at all."),
        # still no scope check on the regenerate pass
        AIMessage(content="Past performance doesn't guarantee future returns; diversify and consider your risk tolerance."),
    )
    fakes["eval"].queue(
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=False, severity="needs_rewrite", issue="unqualified guaranteed-return language"),
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=True, severity="none"),
    )

    app = _graph()
    config = {"configurable": {"thread_id": "general-compliance"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="is this fund a sure thing?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert "no risk at all" not in final_ai.content.lower()
    assert "diversify" in final_ai.content.lower()
    # the non-compliant draft must not be visible anywhere in final history
    assert not any("no risk at all" in (m.content or "") for m in result["messages"])


def test_pii_is_redacted_before_any_specialist_sees_it(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)

    fakes["triage"].queue(RoutingDecision(destination="general"))
    fakes["general"].queue(  # triage just routed here - no scope check
        AIMessage(content="I can't help verify SSNs, but I can answer general questions."),
    )
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""), ComplianceCheck(compliant=True, severity="none"))

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

    # confirm neither triage's nor the specialist's prompt ever saw the raw SSN
    for call in fakes["triage"].calls + fakes["general"].calls:
        assert not any("123-45-6789" in (m.content or "") for m in call)


def test_handoff_from_resumed_specialist_routes_once_without_bouncing(monkeypatch):
    fakes = _patch_all_llms(monkeypatch)
    app = _graph()
    config = {"configurable": {"thread_id": "no-bounce"}}
    # the session already belongs to the market researcher from an earlier turn
    run_async(app.aupdate_state(config, {"messages": [], "current_agent": "market_researcher"}))

    fakes["market_researcher"].queue(MarketScope(in_scope=False))
    fakes["triage"].queue(RoutingDecision(destination="general"))
    # general answers straight away - triage just routed here, so no second scope check
    fakes["general"].queue(AIMessage(content="Bonds pay fixed coupons; prices fall when yields rise."))
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""), ComplianceCheck(compliant=True, severity="none"))

    result = run_async(app.ainvoke(
        {"messages": [HumanMessage(content="how do bonds work?")], "scope_checked": False}, config=config))

    assert result["current_agent"] == "general"
    assert len(fakes["triage"].calls) == 1
    assert len(fakes["general"].calls) == 1
