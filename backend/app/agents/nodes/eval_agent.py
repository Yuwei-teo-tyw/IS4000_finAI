"""
Eval Agent subagent - reviews the specialist/triage agent's response before
it's returned to the user. The producing agent feeds its output here; the
eval agent decides one of:

  - approve:    ship the response as-is
  - regenerate: reject it and send it back to the same agent with feedback,
                 up to MAX_REGENERATIONS times before giving up and shipping
                 the last attempt anyway (never blocks the user forever)
  - flag:       usable, but append a visible caveat before shipping

This is architecturally a separate agent (its own LLM call, its own node in
the graph) that the main agent's output is routed through - not a helper
function called inline by the specialists.

For finance responses specifically, a second structured check runs
alongside the quality verdict: a compliance pass looking for things like
unqualified "guaranteed returns" language, missing disclaimers, or
responses that read as personalized advice rather than general education.
This is a placeholder implementation - it catches obvious cases via an LLM
judgment call, not a substitute for a real compliance review process
(licensed-advisor sign-off, a maintained rules engine, logged audit trail,
etc.) before this is used for anything beyond a demo/prototype.
"""
from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph.message import RemoveMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.prompts.prompt_builder import get_prompt

MAX_REGENERATIONS = 2


class EvalVerdict(BaseModel):
    verdict: Literal["approve", "regenerate", "flag"] = Field(
        description=(
            "'approve' if the response directly and reasonably addresses the user's message. "
            "'regenerate' if it's off-topic, unhelpful, contradicts the conversation, or clearly "
            "fails to answer the question - and trying again could plausibly fix it. "
            "'flag' if the response is usable but has a caveat worth surfacing to the user."
        )
    )
    feedback: str = Field(description="One or two sentences: what's wrong (if anything) and what to fix.")


class ComplianceCheck(BaseModel):
    """Placeholder compliance pass for finance responses only."""
    compliant: bool = Field(
        description=(
            "False if the response contains unqualified 'guaranteed returns'/'risk-free' style "
            "language, gives specific personalized investment/trading instructions (e.g. 'you "
            "should buy X now') rather than general education, or omits an appropriate disclaimer "
            "for advice-adjacent content."
        )
    )
    severity: Literal["none", "needs_disclaimer", "needs_rewrite"] = Field(
        description=(
            "'none' if compliant. 'needs_disclaimer' if the content itself is fine but should "
            "carry an explicit not-personalized-advice caveat. 'needs_rewrite' if the response "
            "makes guarantees or gives direct personalized instructions and should be regenerated."
        )
    )
    issue: Optional[str] = Field(default=None, description="What's non-compliant, if anything.")


class EvalAgent:
    """Quality-control subagent for specialist/triage responses."""

    def __init__(self):
        self.llm = get_groq_model()
        self.evaluator = self.llm.with_structured_output(EvalVerdict)
        self.compliance_checker = self.llm.with_structured_output(ComplianceCheck)

    async def _check_compliance(self, response_text: str) -> Optional[ComplianceCheck]:
        try:
            return await self.compliance_checker.ainvoke([
                SystemMessage(content=get_prompt("eval.compliance_system")),
                HumanMessage(content=f"Assistant response to review:\n\n{response_text}"),
            ])
        except Exception as e:
            print(f"EVAL: compliance check failed, skipping: {e}")
            return None

    async def run(self, state: AgentState) -> Dict[str, Any]:
        messages = state["messages"]
        human_messages = [m for m in messages if m.type == "human"]
        ai_messages = [m for m in messages if m.type == "ai" and m.content]

        if not human_messages or not ai_messages:
            return {"eval_verdict": "approve", "eval_retry_count": 0, "eval_feedback": None}

        latest_user_message = human_messages[-1].content
        latest_response = ai_messages[-1]

        retry_count = state.get("eval_retry_count", 0) or 0
        if retry_count >= MAX_REGENERATIONS:
            # Stop trying to improve it further - ship what we have rather than loop forever.
            print(f"EVAL: max regenerations ({MAX_REGENERATIONS}) reached, approving as-is")
            return {"eval_verdict": "approve", "eval_retry_count": 0, "eval_feedback": None}

        try:
            result = await self.evaluator.ainvoke([
                SystemMessage(content=get_prompt("eval.quality_system")),
                HumanMessage(content=(
                    f"User asked: {latest_user_message}\n\n"
                    f"Assistant responded: {latest_response.content}"
                )),
            ])
            verdict, feedback = result.verdict, result.feedback
        except Exception as e:
            print(f"EVAL: evaluation call failed, approving by default: {e}")
            verdict, feedback = "approve", ""

        # Compliance pass - finance responses only. Can only make things stricter
        # than the quality verdict (approve -> flag/regenerate), never looser.
        compliance = None
        if state.get("current_agent") in ("finance", "market_researcher") and verdict != "regenerate":
            compliance = await self._check_compliance(latest_response.content)

        if compliance and compliance.severity == "needs_rewrite":
            verdict = "regenerate"
            feedback = f"[Compliance] {compliance.issue or 'Contains non-compliant language.'}"
        elif compliance and compliance.severity == "needs_disclaimer" and verdict == "approve":
            verdict = "flag"
            feedback = compliance.issue or "This is general information, not personalized financial advice."

        print(f"EVAL: verdict={verdict} | {feedback}")

        if verdict == "regenerate":
            removals = [RemoveMessage(id=latest_response.id)] if latest_response.id else []
            return {
                "messages": removals,
                "eval_verdict": "regenerate",
                "eval_retry_count": retry_count + 1,
                "eval_feedback": feedback,
            }

        if verdict == "flag":
            removals = [RemoveMessage(id=latest_response.id)] if latest_response.id else []
            flagged_content = f"{latest_response.content}\n\n_⚠️ {feedback}_"
            return {
                "messages": removals + [AIMessage(content=flagged_content)],
                "eval_verdict": "flag",
                "eval_retry_count": 0,
                "eval_feedback": None,
            }

        return {"eval_verdict": "approve", "eval_retry_count": 0, "eval_feedback": None}
