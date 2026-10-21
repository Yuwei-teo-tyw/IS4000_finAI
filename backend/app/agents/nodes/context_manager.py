"""
Context Manager subagent - keeps the conversation window from growing
unbounded. Runs once at the start of every graph invocation (before
routing to triage/market_researcher/general); if the accumulated history is over
budget, it summarizes the older portion and drops those messages from
state, keeping a fixed window of the most recent messages verbatim.

Compaction is real state mutation, not a cosmetic trim: it uses
LangGraph's `RemoveMessage` so the dropped messages are actually removed
from the checkpointed state (and therefore from every future LLM call's
context), not just hidden from this one prompt.
"""
from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
from langgraph.graph.message import RemoveMessage
from app.core import get_groq_model
from app.agents.state import AgentState
from app.prompts.prompt_builder import get_prompt

# Groq/Llama doesn't expose a tokenizer here, so this is a conservative
# chars-per-token approximation - it only needs to catch runaway
# conversations, not be exact.
CHARS_PER_TOKEN_ESTIMATE = 4
TOKEN_BUDGET = 6000            # compact once estimated tokens exceed this
KEEP_RECENT_MESSAGES = 8       # always keep the last N messages verbatim


def _estimate_tokens(messages: List[BaseMessage]) -> int:
    total_chars = sum(len(m.content) for m in messages if isinstance(m.content, str))
    return total_chars // CHARS_PER_TOKEN_ESTIMATE


class ContextManager:
    """Compacts conversation history when it grows too large."""

    def __init__(self):
        self.llm = get_groq_model()

    async def run(self, state: AgentState) -> Dict[str, Any]:
        messages = state["messages"]

        if len(messages) <= KEEP_RECENT_MESSAGES:
            return {}

        estimated_tokens = _estimate_tokens(messages)
        if estimated_tokens <= TOKEN_BUDGET:
            return {}

        to_summarize = messages[:-KEEP_RECENT_MESSAGES]
        if not to_summarize:
            return {}

        transcript = "\n".join(
            f"{'User' if m.type == 'human' else 'Assistant' if m.type == 'ai' else m.type}: {m.content}"
            for m in to_summarize
            if isinstance(m.content, str) and m.content
        )

        if not transcript.strip():
            return {}

        try:
            summary_response = await self.llm.ainvoke([
                SystemMessage(content=get_prompt("context_manager.summarize_system")),
                HumanMessage(content=transcript),
            ])
            summary_text = summary_response.content
        except Exception as e:
            print(f"CONTEXT MANAGER: summarization failed, skipping compaction: {e}")
            return {}

        removals = [RemoveMessage(id=m.id) for m in to_summarize if m.id is not None]
        summary_message = SystemMessage(content=f"[Earlier conversation summary]: {summary_text}")

        print(
            f"CONTEXT MANAGER: compacted {len(to_summarize)} messages "
            f"(~{estimated_tokens} est. tokens) into a summary"
        )

        return {"messages": removals + [summary_message]}
