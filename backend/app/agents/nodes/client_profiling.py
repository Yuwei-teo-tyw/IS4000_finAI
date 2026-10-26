"""
Client Profiling node - chat entry to the Client Profiling agent
(app/agents/client_profiling/), which answers questions about the client in
focus from that client's meeting notes.

No LLM call happens in this node itself: `handle_chat` makes its own (blocking)
local-model calls, so it runs in a worker thread, and its ToolResult is
rendered deterministically to Markdown - nothing is invented here. The book
is restricted to the workspace client so another client's notes can never be
served, even if the message names someone else.
"""
import asyncio
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from app.agents.client_profiling.service import handle_chat
from app.agents.state import AgentState

NO_CLIENT_TEXT = "Please select or open a client first, then ask again about their meeting notes."
FALLBACK_TEXT = "I could not answer that from the client's meeting notes."


def _bullet_text(b: Any) -> str:
    return str(b.get("text", "")) if isinstance(b, dict) else str(b)


def _render_sections(sections: List[Any]) -> List[str]:
    lines: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "").strip()
        bullets = [t for t in (_bullet_text(b).strip() for b in sec.get("bullets") or []) if t]
        if heading:
            lines += [f"### {heading}", ""]
        lines += [f"- {t}" for t in bullets]
        lines.append("")
    return lines


def _render_summary(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    if summary.get("degraded") and summary.get("notice"):
        lines += [str(summary["notice"]), ""]
    sections = summary.get("sections")
    if sections:
        lines += _render_sections(sections)
    else:
        for m in summary.get("meetings") or []:
            if not isinstance(m, dict):
                continue
            title = " - ".join(x for x in (m.get("date"), m.get("title")) if x)
            if title:
                lines += [f"### {title}", ""]
            lines += _render_sections(m.get("sections") or [])
    return "\n".join(lines).strip()


def _sources_line(result) -> str:
    dates = []
    refs = list(result.sources or [])
    for s in (result.data.get("answer") or {}).get("sources") or []:
        if isinstance(s, dict):
            dates.append(s.get("date"))
    dates += [r.date for r in refs]
    seen = []
    for d in dates:
        if d and d not in seen:
            seen.append(d)
    return f"Sources: {', '.join(seen)}" if seen else ""


def render_tool_result(result) -> str:
    """Markdown for a ToolResult (client_profiling.schemas.ToolResult)."""
    data = result.data or {}
    summary = data.get("summary")
    if isinstance(summary, dict) and (summary.get("sections") or summary.get("meetings")):
        body = _render_summary(summary)
        if body:
            return body
    answer = data.get("answer") or {}
    text = (answer.get("text") or "").strip() if isinstance(answer, dict) else ""
    if text and result.tool not in ("out_of_scope", "access_denied"):
        src = _sources_line(result)
        return f"{text}\n\n{src}" if src else text
    if result.message:
        msg = result.message
        if result.status == "needs_clarification" and result.candidates:
            names = ", ".join(c.get("name") or c.get("id", "") for c in result.candidates)
            msg = f"{msg} Candidates: {names}"
        return msg
    return FALLBACK_TEXT


class ClientProfilingNode:
    """Specialist node wrapping the Client Profiling service."""

    async def run(self, state: AgentState) -> Dict[str, Any]:
        human_messages = [m for m in state["messages"] if m.type == "human"]
        latest = human_messages[-1].content if human_messages else ""
        client_id = (state.get("client_id") or "").strip() or None

        base = {
            "current_agent": "client_profiling",
            "next_agent": None,
            "conversation_ended": False,
            "handoff_message": None,
            "skip_eval": True,
        }
        if not client_id:
            return {**base, "messages": [AIMessage(content=NO_CLIENT_TEXT)]}

        try:
            result = await asyncio.to_thread(handle_chat, latest, client_id, book=[client_id])
        except Exception as e:
            print(f"CLIENT_PROFILING: handle_chat failed: {e}")
            return {**base, "messages": [AIMessage(content="I couldn't read this client's meeting notes right now. Please try again.")]}

        if result.tool == "out_of_scope":
            return {**base, "current_agent": "general", "next_agent": "general", "scope_checked": True, "skip_eval": False}

        return {**base, "messages": [AIMessage(content=render_tool_result(result))]}
