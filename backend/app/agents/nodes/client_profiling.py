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
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage

from app.agents.client_profiling.service import handle_chat
from app.agents.state import AgentState

NO_CLIENT_TEXT = "Please select or open a client first, then ask again about their meeting notes or IPS."
FALLBACK_TEXT = "I could not answer that from the client's meeting notes or IPS."


_BOTH = re.compile(r"\b(both|each|either|all)\b", re.I)
_IPS = re.compile(r"\bips\b|investment policy", re.I)
_NOTES = re.compile(r"\b(meeting|notes?|calls?)\b", re.I)


def parse_source_choice(reply: str) -> Optional[str]:
    """The adviser's answer to "Do you mean the meeting notes or the IPS?": notes | ips | both, else None."""
    text = (reply or "").strip()
    if not text or len(text) > 60:  # a real question, not a short pick
        return None
    ips, notes = bool(_IPS.search(text)), bool(_NOTES.search(text))
    if (ips and notes) or (_BOTH.search(text) and (ips or notes or len(text.split()) <= 2)):
        return "both"
    return "ips" if ips else "notes" if notes else None


def _bullet_text(b: Any) -> str:
    return str(b.get("text", "")) if isinstance(b, dict) else str(b)


def _bullet_dates(b: Any) -> str:
    """" (meeting 2026-03-18, 2026-04-02)" from a summary bullet's sources, so every bullet cites its meeting date."""
    dates: List[str] = []
    for src in (b.get("sources") or []) if isinstance(b, dict) else []:
        d = src.get("date") if isinstance(src, dict) else None
        if d and d not in dates:
            dates.append(str(d))
    return f" (meeting {', '.join(dates)})" if dates else ""


def _render_card(card: Any) -> List[str]:
    items = [i for i in (card.get("items") or []) if isinstance(i, dict) and i.get("label")] if isinstance(card, dict) else []
    if not items:
        return []
    return [f"### Profile - {card.get('title') or 'Client'}", ""] + [f"- {i['label']}: {i.get('value')}" for i in items] + [""]


def _render_sections(sections: List[Any]) -> List[str]:
    lines: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "").strip()
        bullets = [t + _bullet_dates(b) for t, b in ((_bullet_text(b).strip(), b) for b in sec.get("bullets") or []) if t]
        if heading:
            lines += [f"### {heading}", ""]
        lines += [f"- {t}" for t in bullets]
        lines.append("")
    return lines


def _render_summary(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    if summary.get("degraded") and summary.get("notice"):
        lines += [str(summary["notice"]), ""]
    lines += _render_card(summary.get("profile_card"))
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


def _src_label(s: Any) -> str:
    kind = s.get("type") if isinstance(s, dict) else getattr(s, "type", None)
    date = s.get("date") if isinstance(s, dict) else getattr(s, "date", None)
    label = s.get("label") if isinstance(s, dict) else getattr(s, "label", "")
    return (label or "IPS") if kind == "ips" else (date or "")


def _sources_line(result_or_answer, prefix: str = "Sources") -> str:
    """"Sources: <note dates>" for notes; IPS refs are named by their label (e.g. "IPS v1")."""
    if isinstance(result_or_answer, dict):
        raw = list(result_or_answer.get("sources") or [])
    else:
        raw = list((result_or_answer.data.get("answer") or {}).get("sources") or []) + list(result_or_answer.sources or [])
    seen: List[str] = []
    for s in raw:
        lab = _src_label(s)
        if lab and lab not in seen:
            seen.append(lab)
    return f"{prefix}: {', '.join(seen)}" if seen else ""


def _render_block(label: str, block: Dict[str, Any]) -> List[str]:
    ans = block.get("answer") or {}
    text = (ans.get("text") or "").strip() or "No answer available."
    lines = [f"### {label}", "", text]
    src = _sources_line(ans, f"Source ({label})")
    return lines + ([src] if src else []) + [""]


def _render_compare(data: Dict[str, Any]) -> str:
    both = data.get("both") or {}
    lines: List[str] = []
    for key, default in (("notes", "Meeting notes"), ("ips", "IPS")):
        blk = both.get(key) or {}
        lines += _render_block(blk.get("label") or default, blk)
    return "\n".join(lines).strip()


def _render_clarify(result) -> str:
    opts = [str(o.get("label")) for o in (result.data or {}).get("options") or [] if isinstance(o, dict) and o.get("label")]
    return f"{result.message} Reply with: {', '.join(opts)}." if opts else result.message


def render_tool_result(result) -> str:
    """Markdown for a ToolResult (client_profiling.schemas.ToolResult)."""
    data = result.data or {}
    if result.tool == "compare_sources" and data.get("both"):
        return _render_compare(data)
    if result.tool == "clarify_source":
        return _render_clarify(result)
    answer = data.get("answer") or {}
    text = (answer.get("text") or "").strip() if isinstance(answer, dict) else ""
    summary = data.get("summary")
    if isinstance(summary, dict) and (summary.get("sections") or summary.get("meetings")):
        body = _render_summary(summary)
        if body:
            if text and result.tool not in ("out_of_scope", "access_denied"):  # question + summary: answer first, then the summary
                src = _sources_line(result)
                body = "\n\n".join(x for x in (text, src, body) if x)
            return body
    if text and result.tool not in ("out_of_scope", "access_denied"):
        src = _sources_line(result)
        inf = answer.get("inference") if isinstance(answer, dict) else None
        inf_text = (inf.get("text") or "").strip() if isinstance(inf, dict) else ""
        return "\n\n".join(x for x in (text, src, inf_text) if x)
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
        pending = state.get("pending_source_question")
        choice = parse_source_choice(latest) if pending else None

        base = {
            "current_agent": "client_profiling",
            "next_agent": None,
            "conversation_ended": False,
            "handoff_message": None,
            "skip_eval": True,
            "pending_source_question": None,
        }
        if not client_id:
            return {**base, "messages": [AIMessage(content=NO_CLIENT_TEXT)]}

        try:
            if choice:  # the adviser answered "which source?": re-ask the ORIGINAL question against that source
                result = await asyncio.to_thread(handle_chat, pending, client_id, book=[client_id], source=choice)
            else:
                result = await asyncio.to_thread(handle_chat, latest, client_id, book=[client_id])
        except Exception as e:
            print(f"CLIENT_PROFILING: handle_chat failed: {e}")
            return {**base, "messages": [AIMessage(content="I couldn't read this client's records right now. Please try again.")]}

        if result.tool == "out_of_scope":
            return {**base, "current_agent": "general", "next_agent": "general", "scope_checked": True, "skip_eval": False}

        out = {**base, "messages": [AIMessage(content=render_tool_result(result))]}
        if result.tool == "clarify_source":  # ask first; the next turn resumes here with the chosen source
            out["pending_source_question"] = latest
        return out
