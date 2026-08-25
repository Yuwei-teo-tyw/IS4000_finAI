"""
State management for the multi-agent system - built on LangGraph's native
message-state pattern instead of a hand-rolled Message class.
"""
from typing import TypedDict, Optional, Dict, Any, Annotated, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    State shared across all nodes in the graph.

    `messages` uses LangGraph's `add_messages` reducer: nodes return only the
    *new* messages they produced and LangGraph appends them to the running
    history automatically (instead of us manually doing `state["messages"] + [...]`
    everywhere, which was the old pattern and easy to get wrong). It also
    lets nodes remove specific messages via `RemoveMessage(id=...)`, which is
    how the context manager compacts history and the eval agent discards a
    rejected response.
    """
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: Optional[str]
    next_agent: Optional[str]
    technical_response: Optional[Dict[str, Any]]
    finance_response: Optional[Dict[str, Any]]
    conversation_ended: bool
    handoff_message: Optional[str]

    # Eval-agent loop control
    eval_verdict: Optional[str]        # "approve" | "regenerate" | "flag"
    eval_feedback: Optional[str]       # reviewer's note, fed back to the agent on a retry
    eval_retry_count: int
    skip_eval: bool                    # True only for canned/templated responses (e.g. the intro)
    pii_redacted: bool                 # True if PIIGuard scrubbed something from the latest message


class TechnicalResponseData(TypedDict):
    message_result: str
    data: Dict[str, Any]


class FinanceResponseData(TypedDict):
    message_result: str
    data: Dict[str, Any]


class SystemResponse(TypedDict):
    technical_response: TechnicalResponseData
    finance_response: FinanceResponseData
    message: str
    agent_name: Optional[str]
    info_message: Optional[str]
