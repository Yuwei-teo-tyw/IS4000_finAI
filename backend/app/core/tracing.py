"""
Langfuse tracing setup.

Langfuse's LangChain/LangGraph integration is a single `CallbackHandler`
passed into the top-level `graph.ainvoke(..., config={"callbacks": [...]})`
call - LangGraph propagates callbacks through its execution context
automatically, so every node's LLM calls (triage, technical, finance, eval,
context manager, compliance check) get traced as one tree per turn without
needing to touch every node file individually.

Configure via the standard Langfuse env vars (unset = tracing silently
no-ops, nothing else breaks):

    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
"""
import os
from typing import Any, Dict, List, Optional
from langfuse.langchain import CallbackHandler

_handler: Optional[CallbackHandler] = None


def get_langfuse_handler() -> CallbackHandler:
    """Shared CallbackHandler instance. Safe to call even with no Langfuse
    credentials configured - the client just runs disabled and traces are
    dropped rather than raising."""
    global _handler
    if _handler is None:
        _handler = CallbackHandler()
    return _handler


def tracing_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY"))


def build_trace_config(
    session_id: str,
    recursion_limit: int,
    tags: Optional[List[str]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the config dict passed to graph.ainvoke(), wiring in the
    Langfuse callback and grouping every turn in a session under one
    Langfuse session (`thread_id` doubles as `langfuse_session_id`)."""
    metadata: Dict[str, Any] = {
        "langfuse_session_id": session_id,
        "langfuse_tags": tags or ["fin-ai-agents"],
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": recursion_limit,
        "callbacks": [get_langfuse_handler()],
        "metadata": metadata,
    }
