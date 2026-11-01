"""
Per-run LLM traceability. `run_trace()` opens a RunTrace for one pipeline run;
it travels in a context variable, so the planner, tagging, explainer and
synthesis stages (including their concurrent tasks) reach it without passing
it through every call.

- `trace_config()` is the config for one LLM call: Langfuse callback and
  metadata carrying the run id and the resolved prompt versions. In chat the
  graph's handler is already inherited; a background HTTP run has none, so it
  is attached here (the shared handler is only registered once).
- `record_attempt()` / `record_failure()` log every attempt, with the rejected
  text, into `output.llm_attempts`. An attempt that wasn't accepted is also a
  WARNING in the server log.

Outside a run (direct calls in tests or scripts) these record nothing.
"""
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

from app.agents.market_researcher.schemas import LlmAttempt, RunOrigin
from app.core.tracing import get_langfuse_handler, tracing_enabled
from app.prompts.prompt_builder import get_prompt_version


logger = logging.getLogger("market_researcher")


@dataclass
class RunTrace:
    run_id: str
    origin: Optional[RunOrigin] = None
    attempts: list[LlmAttempt] = field(default_factory=list)


_current: ContextVar[Optional[RunTrace]] = ContextVar("market_research_run_trace", default=None)


@contextmanager
def run_trace(run_id: str, origin: Optional[RunOrigin] = None) -> Iterator[RunTrace]:
    trace = RunTrace(run_id, origin)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def run_label() -> str:
    """The current run id, for log lines from stages that don't otherwise know it."""
    trace = _current.get()
    return trace.run_id if trace else "-"


def next_attempt(stage: str) -> int:
    trace = _current.get()
    return 1 + sum(a.stage == stage for a in trace.attempts) if trace else 1


def trace_config(stage: str, prompt_keys: Iterable[str]) -> dict:
    """Config for one LLM call in `stage`."""
    trace = _current.get()
    metadata: dict = {
        "langfuse_tags": ["fin-ai-agents", "market-researcher", stage],
        "prompt_versions": {k: get_prompt_version(k) for k in prompt_keys},
        "attempt": next_attempt(stage),
    }
    if trace:
        metadata["market_run_id"] = trace.run_id
        metadata["langfuse_session_id"] = (trace.origin and trace.origin.session_id) or trace.run_id
    return {"run_name": f"market_researcher.{stage}", "metadata": metadata,
            "callbacks": [get_langfuse_handler()] if tracing_enabled() else []}


def record_attempt(stage: str, started: float, problems: Iterable[str] = (), rejected_text: Optional[str] = None,
                   outcome: Optional[str] = None) -> None:
    """Log an attempt that returned; it counts as rejected if it has problems,
    unless `outcome` says otherwise."""
    trace = _current.get()
    if trace is None:
        return
    found = list(problems)
    entry = LlmAttempt(
        stage=stage, attempt=next_attempt(stage), outcome=outcome or ("rejected" if found else "accepted"),
        latency_ms=int((time.monotonic() - started) * 1000), problems=found, rejected_text=rejected_text,
    )
    trace.attempts.append(entry)
    if entry.outcome != "accepted":
        logger.warning("run=%s stage=%s attempt=%d outcome=%s problems=%.300s",
                       trace.run_id, stage, entry.attempt, entry.outcome, "; ".join(found))


def record_failure(stage: str, started: float, error: BaseException) -> None:
    """Log an attempt that raised or timed out."""
    timed_out = isinstance(error, TimeoutError)
    record_attempt(stage, started, [type(error).__name__], outcome="timeout" if timed_out else "error")
