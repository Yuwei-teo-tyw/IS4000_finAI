"""
HumanApprovalGate: the hard confirmation gate in front of any
money-moving action the finance agent proposes.

`interrupt()` only behaves correctly inside an actual LangGraph run (it
raises a `GraphInterrupt` that the runtime catches and turns into
`__interrupt__` on the result) - so the interrupt/resume-cycle tests build
a minimal single-node graph around the real `HumanApprovalGate`, backed by
an in-memory checkpointer, rather than calling `.run()` directly.
"""
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.nodes.human_approval import ACTION_TOOL_NAME, HumanApprovalGate, _find_action_call
from app.agents.state import AgentState

from conftest import run_async

ACTION_ARGS = {"action_type": "transfer", "amount": 500.0, "description": "move $500 to savings"}


def _action_message(call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": ACTION_TOOL_NAME, "args": ACTION_ARGS, "id": call_id}])


def _build_gate_graph():
    gate = HumanApprovalGate()
    workflow = StateGraph(AgentState)
    workflow.add_node("human_approval", gate.run)
    workflow.add_edge(START, "human_approval")
    workflow.add_edge("human_approval", END)
    return workflow.compile(checkpointer=InMemorySaver())


def test_find_action_call_detects_proposed_action():
    assert _find_action_call(_action_message())["name"] == ACTION_TOOL_NAME


def test_find_action_call_ignores_other_tool_calls():
    other = AIMessage(content="", tool_calls=[{"name": "tavily_search", "args": {}, "id": "c1"}])
    assert _find_action_call(other) is None


def test_gate_run_is_noop_without_an_action_call():
    gate = HumanApprovalGate()
    state = {"messages": [AIMessage(content="just a normal reply")]}
    assert run_async(gate.run(state)) == {}


def test_graph_pauses_with_interrupt_payload_for_a_proposed_action():
    app = _build_gate_graph()
    config = {"configurable": {"thread_id": "session-1"}}

    result = run_async(app.ainvoke({"messages": [_action_message()]}, config=config))

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm_financial_action"
    assert payload["action"] == ACTION_ARGS
    assert "transfer" in payload["message"]


def test_resume_with_approval_produces_approved_tool_message():
    app = _build_gate_graph()
    config = {"configurable": {"thread_id": "session-approve"}}
    run_async(app.ainvoke({"messages": [_action_message(call_id="call-42")]}, config=config))

    result = run_async(app.ainvoke(Command(resume=True), config=config))

    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.tool_call_id == "call-42"
    assert "approved" in tool_msg.content.lower()


def test_resume_with_decline_produces_declined_tool_message_and_executes_nothing():
    app = _build_gate_graph()
    config = {"configurable": {"thread_id": "session-decline"}}
    run_async(app.ainvoke({"messages": [_action_message(call_id="call-99")]}, config=config))

    result = run_async(app.ainvoke(Command(resume=False), config=config))

    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.tool_call_id == "call-99"
    assert "declined" in tool_msg.content.lower()
    assert "nothing was executed" in tool_msg.content.lower()
