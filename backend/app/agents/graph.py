"""
Multi-agent graph built on LangGraph's StateGraph.

Graph shape:

    START --> pii_guard --> context_manager --(entry_router: resumes with whichever agent owned the session)--> triage | market_researcher | general

    triage    --(route_after_triage)-->    market_researcher | general | END
    general   --(route_after_general)-->   general_tools | triage (handoff) | eval | END
    market_researcher --(route_after_market_researcher)--> triage (handoff) | eval | END
    general_tools   --> general     (loop back with tool results)

    eval --(route_after_eval)--> market_researcher | general | triage (regenerate) | END (approved/flagged)

Subagents wrapping the core triage/specialist flow:

- `pii_guard`: scans the incoming user message for likely PII (SSNs, emails,
  account/card numbers) and redacts it before anything downstream sees it.
  Placeholder regex-based implementation - see nodes/pii_guard.py.
- `context_manager`: compacts conversation history once it grows too large
  (see nodes/context_manager.py).
- `eval`: reviews every final response before it ships - can approve, flag
  with a caveat, or send it back for a regenerate with feedback. Runs an
  additional compliance pass, since both specialists can touch financial
  topics (see nodes/eval_agent.py).

Session state (including full message history) is kept by a LangGraph
checkpointer, keyed by `thread_id` = our session_id. The checkpointer itself
is built in app.py's lifespan (an `AsyncPostgresSaver`, so state survives
process restarts and is shared across workers) and injected into
`build_graph()`/`MultiAgentGraph` here rather than constructed in this
module - Postgres needs an open connection managed for the app's whole
lifetime, which doesn't fit a plain module-level singleton.
"""
from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.state import AgentState
from app.agents.client_context import format_client_context
from app.agents.nodes.triage import TriageAgent
from app.agents.nodes.general import GeneralAssistant
from app.agents.nodes.market_researcher import MarketResearcher
from app.agents.nodes.context_manager import ContextManager
from app.agents.nodes.eval_agent import EvalAgent
from app.agents.nodes.pii_guard import PIIGuard
from app.agents.tools import tavily_search
from app.core.tracing import build_trace_config


AGENT_DISPLAY_NAMES = {
    "triage": "Triage Agent",
    "general": "General Assistant",
    "market_researcher": "Market Researcher",
}

SPECIALISTS = ("market_researcher", "general")

EMPTY_RESPONSE = {"message_result": "", "data": {}}

# Generous headroom for compaction / tool-call loops / eval regenerate loops
# stacking within a single turn.
RECURSION_LIMIT = 40


def entry_router(state: AgentState) -> str:
    """Which node handles a *new incoming message* for this session.

    If the session was already talking to a specialist, resume there
    directly instead of re-routing through triage every turn.
    """
    agent = state.get("current_agent")
    if agent in SPECIALISTS:
        return agent
    return "triage"


def route_after_triage(state: AgentState) -> str:
    next_agent = state.get("next_agent")
    if next_agent in SPECIALISTS:
        return next_agent
    return END  # canned/templated response (e.g. the intro) - nothing to review


def route_after_general(state: AgentState) -> str:
    if state.get("next_agent") == "triage":
        return "triage"  # handoff, nothing to eval yet
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "general_tools"
    if state.get("skip_eval"):
        return END
    return "eval"  # final answer - review it before shipping


def route_after_market_researcher(state: AgentState) -> str:
    if state.get("next_agent") == "triage":
        return "triage"  # handoff, nothing to eval yet
    if state.get("skip_eval"):
        return END
    return "eval"  # rendered pipeline output - still gets the compliance review


def route_after_eval(state: AgentState) -> str:
    if state.get("eval_verdict") == "regenerate":
        agent = state.get("current_agent")
        if agent in (*SPECIALISTS, "triage"):
            return agent
    return END


def build_graph(checkpointer: BaseCheckpointSaver):
    triage_agent = TriageAgent()
    general_agent = GeneralAssistant()
    market_agent = MarketResearcher()
    context_manager = ContextManager()
    eval_agent = EvalAgent()
    pii_guard = PIIGuard()
    search_tools = ToolNode([tavily_search])

    workflow = StateGraph(AgentState)

    workflow.add_node("pii_guard", pii_guard.run)
    workflow.add_node("context_manager", context_manager.run)
    workflow.add_node("triage", triage_agent.run)
    workflow.add_node("general", general_agent.run)
    workflow.add_node("market_researcher", market_agent.run)
    workflow.add_node("general_tools", search_tools)
    workflow.add_node("eval", eval_agent.run)

    workflow.add_edge(START, "pii_guard")
    workflow.add_edge("pii_guard", "context_manager")
    workflow.add_conditional_edges(
        "context_manager", entry_router,
        {"triage": "triage", **{agent: agent for agent in SPECIALISTS}}
    )
    workflow.add_conditional_edges(
        "triage", route_after_triage,
        {**{agent: agent for agent in SPECIALISTS}, END: END}
    )
    workflow.add_conditional_edges(
        "general", route_after_general,
        {"general_tools": "general_tools", "triage": "triage", "eval": "eval", END: END}
    )
    workflow.add_conditional_edges(
        "market_researcher", route_after_market_researcher,
        {"triage": "triage", "eval": "eval", END: END}
    )
    workflow.add_edge("general_tools", "general")
    workflow.add_conditional_edges(
        "eval", route_after_eval,
        {**{agent: agent for agent in SPECIALISTS}, "triage": "triage", END: END}
    )

    return workflow.compile(checkpointer=checkpointer)


class MultiAgentGraph:
    """Thin wrapper exposing the compiled LangGraph app with the same
    `process_message` contract the FastAPI/WebSocket layer already expects,
    so nothing above this layer had to change.

    Takes a checkpointer rather than constructing one itself: the Postgres
    checkpointer needs an open connection managed for the app's whole
    lifetime (see app.py's lifespan), which can't happen at import time the
    way the old in-memory `MemorySaver()` could.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver):
        self.graph = build_graph(checkpointer)

    def _extract_result(self, result_state: Dict[str, Any]) -> Dict[str, Any]:
        ai_messages = [m for m in result_state["messages"] if m.type == "ai" and m.content]
        final_message = ai_messages[-1].content if ai_messages else ""

        current_agent_internal = result_state.get("current_agent", "System")
        display_name = AGENT_DISPLAY_NAMES.get(current_agent_internal, current_agent_internal)

        return {
            "message": final_message,
            "agent_name": display_name,
            "market_research_response": result_state.get("market_research_response") or EMPTY_RESPONSE,
            "handoff_message": result_state.get("handoff_message"),
        }

    async def process_message(
        self,
        message: str,
        session_id: str = "default",
        websocket_client: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = build_trace_config(session_id, RECURSION_LIMIT)

        try:
            # client_context is set on every turn (None when absent) so a
            # previous turn's workspace context never lingers in the session.
            # scope_checked is reset so the resumed specialist re-checks scope
            # for the new message (see nodes/general.py).
            result_state = await self.graph.ainvoke(
                {
                    "messages": [HumanMessage(content=message)],
                    "client_context": format_client_context(context),
                    "scope_checked": False,
                },
                config=config,
            )
            return self._extract_result(result_state)

        except Exception as e:
            print(f"Error processing message: {e}")
            return {
                "message": f"I apologize, but I encountered an issue processing your request: {str(e)}",
                "agent_name": "System",
                "market_research_response": EMPTY_RESPONSE,
                "handoff_message": None,
            }

    async def get_history(self, session_id: str) -> list[Dict[str, Any]]:
        """Replay a past session's messages for the sidebar - reads straight
        from the checkpointer, no separate message log to keep in sync.

        Only human/final-AI turns are returned (tool calls/results are
        internal plumbing for a turn already represented by the AI message
        that follows them). Historical messages aren't tagged with which
        specialist produced them - that's only tracked for the *current*
        turn in AgentState - so agent_name is omitted here; the frontend
        falls back to a generic label for replayed history.
        """
        config = build_trace_config(session_id, RECURSION_LIMIT)
        snapshot = await self.graph.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot else []

        history: list[Dict[str, Any]] = []
        for m in messages:
            if m.type == "human":
                history.append({"role": "user", "content": m.content})
            elif m.type == "ai" and m.content:
                history.append({"role": "assistant", "content": m.content})
        return history
