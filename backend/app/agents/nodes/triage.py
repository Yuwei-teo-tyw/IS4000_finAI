"""
Triage Agent - Routes requests to appropriate specialists or provides general assistance.

Routing uses `with_structured_output` (a real LangChain/Groq feature) instead
of asking the model to emit a magic string like "ROUTE_TO_TECHNICAL" and then
substring-matching it - that's brittle since a normal answer could coincidentally
contain the substring, and there's no schema validation.

All prompt text lives in app/prompts/prompts.yaml, loaded via prompt_builder -
see that module's docstring for why.
"""
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.prompts.prompt_builder import get_prompt


class RoutingDecision(BaseModel):
    """Routing decision for an incoming user message."""
    destination: Literal["technical", "finance", "general", "meta"] = Field(
        description=(
            "'technical' for programming/coding/debugging/software questions, "
            "'finance' for investment/market/budgeting/financial questions, "
            "'meta' if the user is asking what this assistant/platform can do, which specialists or "
            "agents are available, or for help/options about the platform itself rather than asking "
            "an actual question, "
            "'general' for everything else (general knowledge, conversation, creative requests, "
            "current events/weather/real-time info)."
        )
    )


class TriageAgent:
    """
    AI-powered triage agent that intelligently routes requests to the
    Technical, Finance, or General specialist.
    """

    def __init__(self):
        self.llm = get_groq_model()
        self.router = self.llm.with_structured_output(RoutingDecision)

    def get_agent_introduction(self) -> str:
        """Generate a helpful introduction about available agents and their capabilities"""
        return get_prompt("triage.introduction")

    async def run(self, state: AgentState) -> Dict[str, Any]:
        """Execute the triage agent"""

        human_messages = [m for m in state["messages"] if m.type == "human"]
        latest_message = human_messages[-1].content if human_messages else ""

        # Structured routing decision - validated against the RoutingDecision schema,
        # not a substring match on free text. (A "help" substring check used to run
        # here before routing; it misfired on anything containing the word "help",
        # e.g. "I need coding help" - replaced with a 'meta' routing destination so
        # the same classifier handles it instead of a separate keyword pass.)
        try:
            decision = await self.router.ainvoke([
                SystemMessage(content=get_prompt("triage.routing_system")),
                HumanMessage(content=latest_message),
            ])
            destination = decision.destination
        except Exception as e:
            print(f"TRIAGE: routing error: {e}")
            destination = "general"

        if destination == "meta":
            introduction = self.get_agent_introduction()
            return {
                "messages": [AIMessage(content=introduction)],
                "current_agent": "triage",
                "next_agent": None,
                "conversation_ended": False,
                "handoff_message": None,
                "skip_eval": True,
            }

        if destination == "technical":
            return {
                "current_agent": "technical",
                "next_agent": "technical",
                "conversation_ended": False,
                "handoff_message": "I'll connect you with our Technical Specialist to help with your programming question.",
            }

        if destination == "finance":
            return {
                "current_agent": "finance",
                "next_agent": "finance",
                "conversation_ended": False,
                "handoff_message": "I'll connect you with our Finance Expert to help with your financial question.",
            }

        # Hand off to the General Assistant, which has live web search
        # (tavily_search) for real-time questions - weather, current events,
        # scores - that a plain, tool-less generation couldn't reliably answer.
        return {
            "current_agent": "general",
            "next_agent": "general",
            "conversation_ended": False,
            "handoff_message": None,
        }
