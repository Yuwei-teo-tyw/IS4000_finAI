"""
Human-in-the-loop approval gate (placeholder) - pauses the graph via
LangGraph's `interrupt()` whenever the finance agent proposes a
money-moving action (a call to the `propose_financial_action` tool), and
only proceeds once the human explicitly confirms.

`propose_financial_action` is currently an inert placeholder tool - it
returns a description string, it doesn't touch any real account. But the
approval gate itself is real: wiring in an actual trade/transfer API later
is a drop-in change behind this same node, not a new safety mechanism you
have to go build. Don't remove this gate when that integration happens.
"""
from typing import Dict, Any, Optional
from langgraph.types import interrupt
from langchain_core.messages import ToolMessage, BaseMessage
from app.agents.state import AgentState
from app.prompts.prompt_builder import get_prompt

ACTION_TOOL_NAME = "propose_financial_action"


def _find_action_call(message: BaseMessage) -> Optional[dict]:
    tool_calls = getattr(message, "tool_calls", None) or []
    return next((tc for tc in tool_calls if tc["name"] == ACTION_TOOL_NAME), None)


class HumanApprovalGate:
    """Blocks execution of money-moving tool calls until a human confirms."""

    async def run(self, state: AgentState) -> Dict[str, Any]:
        last = state["messages"][-1]
        action_call = _find_action_call(last)

        if action_call is None:
            # Shouldn't normally get here (the router only sends action-tool
            # calls to this node), but fail safe rather than raise.
            return {}

        approved = interrupt({
            "type": "confirm_financial_action",
            "action": action_call["args"],
            "message": get_prompt(
                "human_approval.confirm_message",
                action_type=action_call["args"].get("action_type", "perform an action"),
                amount=action_call["args"].get("amount", 0),
                description=action_call["args"].get("description", ""),
            ),
        })

        if approved:
            result_text = (
                f"User approved. PLACEHOLDER: no real brokerage/transfer integration is "
                f"wired up yet - this is where that API call would go for: {action_call['args']}"
            )
        else:
            result_text = "User declined. Nothing was executed."

        return {
            "messages": [ToolMessage(content=result_text, tool_call_id=action_call["id"])]
        }
