"""
Finance Expert Agent - handles financial questions and market analysis.

Real tool-calling for search, structured scope classification for handoff
instead of a magic-string marker.

All prompt text lives in app/prompts/prompts.yaml, loaded via prompt_builder.
"""
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.agents.tools import tavily_search, propose_financial_action, generate_client_report
from app.agents.finance_glossary import normalize_financial_terms
from app.prompts.prompt_builder import get_prompt


class ScopeCheck(BaseModel):
    in_scope: bool = Field(
        description="True if this message is a financial/investment/market/budgeting question this specialist should handle."
    )


class FinanceExpert:
    """Specialist agent for handling financial questions and market analysis."""

    def __init__(self):
        self.llm = get_groq_model()
        self.llm_with_tools = self.llm.bind_tools(
            [tavily_search, propose_financial_action, generate_client_report]
        )
        self.scope_checker = self.llm.with_structured_output(ScopeCheck)

    async def run(self, state: AgentState) -> Dict[str, Any]:
        messages = state["messages"]

        resuming_after_tool = bool(messages) and messages[-1].type == "tool"

        if not resuming_after_tool:
            human_messages = [m for m in messages if m.type == "human"]
            latest_message = human_messages[-1].content if human_messages else ""
            # Expand shorthand ("P/E", "YOY", ...) so scope classification
            # isn't tripped up by jargon the model doesn't recognize.
            normalized_message = normalize_financial_terms(latest_message)

            try:
                scope = await self.scope_checker.ainvoke([
                    SystemMessage(content=get_prompt("finance.scope_check_system")),
                    HumanMessage(content=normalized_message),
                ])
                in_scope = scope.in_scope
            except Exception as e:
                print(f"FINANCE: scope check failed: {e}")
                in_scope = True

            if not in_scope:
                return {
                    "current_agent": "triage",
                    "next_agent": "triage",
                    "conversation_ended": False,
                    "handoff_message": "That's outside my area - let me hand you back to the triage agent.",
                }

        history = [SystemMessage(content=get_prompt("finance.system"))] + list(messages)

        eval_feedback = state.get("eval_feedback")
        if eval_feedback:
            history.append(SystemMessage(content=get_prompt("shared.regenerate_note", feedback=eval_feedback)))

        try:
            response = await self.llm_with_tools.ainvoke(history)
        except Exception as e:
            print(f"FINANCE: LLM call failed: {e}")
            response = AIMessage(content="I apologize, but I'm having trouble processing your request right now.")

        # search_used should be True if a search happened at any point *this turn* -
        # either the model is calling the tool right now, or we're the follow-up
        # call after a tool result already came back.
        search_used = bool(getattr(response, "tool_calls", None)) or resuming_after_tool

        finance_response = {
            "message_result": (response.content or "(searching...)")[:150],
            "data": {
                "query_type": "finance",
                "search_used": search_used,
                "disclaimer": get_prompt("finance.disclaimer"),
            },
        }

        return {
            "messages": [response],
            "current_agent": "finance",
            "next_agent": None,
            "conversation_ended": False,
            "finance_response": finance_response,
            "handoff_message": None,
            "skip_eval": False,
        }
