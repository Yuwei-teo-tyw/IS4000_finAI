"""
Technical Specialist Agent - handles programming/technical questions.

Two things changed from the original hand-rolled version:
1. Web search is a real bound tool (`bind_tools`) - the model decides whether
   to call it, instead of a keyword list ("latest", "current", "2026"...)
   deciding for it.
2. Scope/handoff is a structured classification (`with_structured_output`),
   not a "FINISH_CONVERSATION" magic string the model has to remember to emit
   and we regex out of its answer.

All prompt text lives in app/prompts/prompts.yaml, loaded via prompt_builder.
"""
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.agents.tools import tavily_search
from app.prompts.prompt_builder import get_prompt


class ScopeCheck(BaseModel):
    in_scope: bool = Field(
        description="True if this message is a technical/programming/software question this specialist should handle."
    )


class TechnicalSpecialist:
    """Specialist agent for handling technical and programming questions."""

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
                    SystemMessage(content=get_prompt("technical.scope_check_system")),
                    HumanMessage(content=latest_message),
                ])
                in_scope = scope.in_scope
            except Exception as e:
                print(f"TECHNICAL: scope check failed: {e}")
                in_scope = True

            if not in_scope:
                return {
                    "current_agent": "triage",
                    "next_agent": "triage",
                    "conversation_ended": False,
                    "handoff_message": "That's outside my area - let me hand you back to the triage agent.",
                }

        history = [SystemMessage(content=get_prompt("technical.system"))] + list(messages)

        eval_feedback = state.get("eval_feedback")
        if eval_feedback:
            history.append(SystemMessage(content=get_prompt("shared.regenerate_note", feedback=eval_feedback)))

        try:
            response = await self.llm_with_tools.ainvoke(history)
        except Exception as e:
            print(f"TECHNICAL: LLM call failed: {e}")
            response = AIMessage(content="I apologize, but I'm having trouble processing your request right now.")

        # search_used should be True if a search happened at any point *this turn* -
        # either the model is calling the tool right now, or we're the follow-up
        # call after a tool result already came back.
        search_used = bool(getattr(response, "tool_calls", None)) or resuming_after_tool

        technical_response = {
            "message_result": (response.content or "(searching...)")[:150],
            "data": {"query_type": "technical", "search_used": search_used},
        }

        return {
            "messages": [response],
            "current_agent": "technical",
            "next_agent": None,
            "conversation_ended": False,
            "technical_response": technical_response,
            "handoff_message": None,
            "skip_eval": False,
        }
