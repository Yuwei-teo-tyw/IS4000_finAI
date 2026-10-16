"""
General Assistant Agent - handles general knowledge, conversation, and
creative requests that don't need the Finance or Market Researcher specialists.

Mirrors finance.py's pattern in two ways:
1. Real tool-calling for search (`tavily_search`) instead of answering from
   static knowledge alone, so time-sensitive questions (weather, current
   events, scores, recent releases) get an actual answer instead of a stale
   or hallucinated one.
2. A structured scope check, run once per new user message. Sessions resume
   directly on "general" turn after turn (see entry_router in graph.py) once
   triage first routes here, so if the topic then shifts to a financial
   question mid-conversation, this is what hands back to triage to
   re-route - without it the conversation would get stuck narrating a
   handoff ("I'll connect you with our Finance Expert...") that never
   actually happens.

All prompt text lives in app/prompts/prompts.yaml, loaded via prompt_builder.
"""
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.agents.tools import tavily_search
from app.prompts.prompt_builder import get_prompt


class ScopeCheck(BaseModel):
    destination: Literal["finance", "general"] = Field(
        description=(
            "'finance' if this message is actually an investment/market/budgeting/financial question, "
            "'general' if it genuinely belongs here (general knowledge, programming, conversation, creative requests, "
            "current events/weather/real-time info)."
        )
    )


class GeneralAssistant:
    """Catch-all agent for general knowledge, conversation, and creative requests."""

    def __init__(self):
        self.llm = get_groq_model()
        self.llm_with_tools = self.llm.bind_tools([tavily_search])
        self.scope_checker = self.llm.with_structured_output(ScopeCheck)

    async def run(self, state: AgentState) -> Dict[str, Any]:
        messages = state["messages"]

        # If we're resuming right after a tool call executed, skip the scope
        # check (already done this turn) and just continue generating.
        resuming_after_tool = bool(messages) and messages[-1].type == "tool"

        if not resuming_after_tool:
            human_messages = [m for m in messages if m.type == "human"]
            latest_message = human_messages[-1].content if human_messages else ""

            try:
                scope = await self.scope_checker.ainvoke([
                    SystemMessage(content=get_prompt("general.scope_check_system")),
                    HumanMessage(content=latest_message),
                ])
                destination = scope.destination
            except Exception as e:
                print(f"GENERAL: scope check failed: {e}")
                destination = "general"

            if destination == "finance":
                return {
                    "current_agent": "triage",
                    "next_agent": "triage",
                    "conversation_ended": False,
                    "handoff_message": "That's outside my area - let me hand you back to the triage agent.",
                }

        history = [SystemMessage(content=get_prompt("general.system"))] + list(messages)

        eval_feedback = state.get("eval_feedback")
        if eval_feedback:
            history.append(SystemMessage(content=get_prompt("shared.regenerate_note", feedback=eval_feedback)))

        try:
            response = await self.llm_with_tools.ainvoke(history)
        except Exception as e:
            print(f"GENERAL: LLM call failed: {e}")
            response = AIMessage(content="I'm here to help! What would you like to know?")

        return {
            "messages": [response],
            "current_agent": "general",
            "next_agent": None,
            "conversation_ended": False,
            "handoff_message": None,
            "skip_eval": False,
        }
