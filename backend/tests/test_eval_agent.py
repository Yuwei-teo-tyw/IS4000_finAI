"""
EvalAgent: the quality verdict (approve/regenerate/flag), the regeneration
cap, and the finance-only compliance pass layered on top - which can only
make a quality verdict *stricter* (approve -> flag/regenerate), never
looser, and only runs for finance responses that didn't already fail
quality review.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import RemoveMessage

import app.agents.nodes.eval_agent as eval_module
from app.agents.nodes.eval_agent import MAX_REGENERATIONS, ComplianceCheck, EvalAgent, EvalVerdict

from conftest import FakeLLM, run_async


def _make_agent(monkeypatch, fake_llm):
    monkeypatch.setattr(eval_module, "get_groq_model", lambda: fake_llm)
    return EvalAgent()


def _state(current_agent="technical", **overrides):
    base = {
        "messages": [
            HumanMessage(content="what's a good ETF?"),
            AIMessage(content="Consider a broad-market index fund.", id="ai-1"),
        ],
        "current_agent": current_agent,
        "eval_retry_count": 0,
    }
    base.update(overrides)
    return base


def test_approve_non_finance_skips_compliance_pass(monkeypatch):
    fake_llm = FakeLLM(EvalVerdict(verdict="approve", feedback=""))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="technical")))

    assert result["eval_verdict"] == "approve"
    assert result["eval_retry_count"] == 0
    assert len(fake_llm.calls) == 1  # compliance checker never invoked


def test_regenerate_removes_rejected_response_and_bumps_retry_count(monkeypatch):
    fake_llm = FakeLLM(EvalVerdict(verdict="regenerate", feedback="off-topic"))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(eval_retry_count=0)))

    assert result["eval_verdict"] == "regenerate"
    assert result["eval_retry_count"] == 1
    assert result["eval_feedback"] == "off-topic"
    removal = next(m for m in result["messages"] if isinstance(m, RemoveMessage))
    assert removal.id == "ai-1"


def test_flag_appends_caveat_and_resets_retry_count(monkeypatch):
    fake_llm = FakeLLM(EvalVerdict(verdict="flag", feedback="not exhaustive"))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(eval_retry_count=1)))

    assert result["eval_verdict"] == "flag"
    assert result["eval_retry_count"] == 0
    flagged = next(m for m in result["messages"] if isinstance(m, AIMessage))
    assert "not exhaustive" in flagged.content
    assert "Consider a broad-market index fund." in flagged.content


def test_max_regenerations_reached_approves_without_calling_llm(monkeypatch):
    fake_llm = FakeLLM()  # empty queue - any ainvoke call would raise
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(eval_retry_count=MAX_REGENERATIONS)))

    assert result["eval_verdict"] == "approve"
    assert result["eval_retry_count"] == 0
    assert fake_llm.calls == []


def test_finance_compliance_needs_rewrite_overrides_approve_to_regenerate(monkeypatch):
    fake_llm = FakeLLM(
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=False, severity="needs_rewrite", issue="promises guaranteed 20% returns"),
    )
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="finance")))

    assert result["eval_verdict"] == "regenerate"
    assert "[Compliance]" in result["eval_feedback"]
    assert "guaranteed 20% returns" in result["eval_feedback"]


def test_finance_compliance_needs_disclaimer_overrides_approve_to_flag(monkeypatch):
    fake_llm = FakeLLM(
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=False, severity="needs_disclaimer", issue="reads as personalized advice"),
    )
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="finance")))

    assert result["eval_verdict"] == "flag"
    flagged = next(m for m in result["messages"] if isinstance(m, AIMessage))
    assert "reads as personalized advice" in flagged.content


def test_finance_compliance_none_severity_leaves_approve_untouched(monkeypatch):
    fake_llm = FakeLLM(
        EvalVerdict(verdict="approve", feedback=""),
        ComplianceCheck(compliant=True, severity="none"),
    )
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="finance")))

    assert result["eval_verdict"] == "approve"


def test_compliance_pass_skipped_when_quality_already_regenerates(monkeypatch):
    fake_llm = FakeLLM(EvalVerdict(verdict="regenerate", feedback="unhelpful"))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="finance")))

    assert result["eval_verdict"] == "regenerate"
    assert result["eval_feedback"] == "unhelpful"  # not the [Compliance]-prefixed message
    assert len(fake_llm.calls) == 1  # compliance checker never invoked


def test_compliance_check_failure_does_not_block_approval(monkeypatch):
    fake_llm = FakeLLM(EvalVerdict(verdict="approve", feedback=""), RuntimeError("groq down"))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="finance")))

    assert result["eval_verdict"] == "approve"


def test_evaluator_failure_approves_by_default(monkeypatch):
    fake_llm = FakeLLM(RuntimeError("groq down"))
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run(_state(current_agent="technical")))

    assert result["eval_verdict"] == "approve"


def test_no_human_or_ai_messages_approves_trivially(monkeypatch):
    fake_llm = FakeLLM()
    agent = _make_agent(monkeypatch, fake_llm)

    result = run_async(agent.run({"messages": [], "current_agent": "finance", "eval_retry_count": 0}))

    assert result["eval_verdict"] == "approve"
    assert fake_llm.calls == []
