"""
Runs one structured LLM writing job: product reasons or a view narrative.

The LLM gets only engine-computed facts. Each item it returns is checked on
its own; if any fail, the call is retried once with the violations, and an
item that still fails keeps its deterministic text. A provider or parsing
failure is retried once; a timeout is not. If no attempt gives usable text,
every item keeps its deterministic text, with `ExplanationStatus` saying why.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.portfolio_manager.explain.llm_client import LLMUnavailable, get_llm
from app.agents.portfolio_manager.schemas.response import ExplanationStatus
from app.agents.product_recommender.config import Settings
from app.core.tracing import get_langfuse_handler, tracing_enabled
from app.prompts.prompt_builder import get_prompt, get_prompt_version

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
# parsed output -> (accepted text per item id, problems per rejected item id)
Checker = Callable[[Any], tuple[dict[str, Any], dict[str, list[str]]]]


@dataclass
class WriteResult:
    status: ExplanationStatus
    accepted: dict[str, Any] = field(default_factory=dict)


def deterministic_status(detail: str, settings: Settings, attempted: bool = False) -> ExplanationStatus:
    return ExplanationStatus(source="DETERMINISTIC_FALLBACK" if attempted else "DETERMINISTIC", llm_attempted=attempted,
                             llm_succeeded=False, model=settings.llm_model if attempted else None, detail=detail)


def _coerce(schema: type[T], raw: Any) -> T:
    if isinstance(raw, schema):
        return raw
    if isinstance(raw, dict):
        return schema.model_validate(raw)
    content = getattr(raw, "content", raw)  # a bare chat message or a JSON string
    if isinstance(content, str):
        return schema.model_validate_json(content)
    raise ValueError(f"unexpected LLM output type {type(raw).__name__}")


def trace_config(prompt: str, attempt: int, trace_id: str | None) -> dict:
    """Langfuse callback and metadata for one call; the prompt versions show which prompt wrote which text."""
    keys = [f"product_recommender.{prompt}_system", f"product_recommender.{prompt}_user"]
    metadata = {
        "langfuse_tags": ["fin-ai-agents", "product-recommender", prompt],
        "prompt_versions": {k: get_prompt_version(k) for k in keys},
        "attempt": attempt,
    }
    if trace_id:
        metadata["langfuse_session_id"] = trace_id
    return {"run_name": f"product_recommender.{prompt}", "metadata": metadata,
            "callbacks": [get_langfuse_handler()] if tracing_enabled() else []}


def _feedback(problems: dict[str, list[str]]) -> str:
    lines = "; ".join(f"{k}: {', '.join(v[:3])}" for k, v in sorted(problems.items()))
    return get_prompt("shared.regenerate_note", feedback=lines)


async def write(schema: type[T], prompt: str, facts: dict, ids: list[str], check: Checker, settings: Settings,
                llm_factory: Callable = get_llm, trace_id: str | None = None) -> WriteResult:
    """`prompt` names a prompts.yaml section with `{prompt}_system` and `{prompt}_user` keys.
    `trace_id` groups the calls in Langfuse (a request id; never a client id)."""
    try:
        llm = llm_factory(settings)
    except LLMUnavailable as e:
        return WriteResult(deterministic_status(f"LLM not used: {e} Rule-based text provided.", settings))

    messages: list = [
        ("system", get_prompt(f"product_recommender.{prompt}_system")),
        ("human", get_prompt(f"product_recommender.{prompt}_user", facts_json=json.dumps(facts, default=str))),
    ]
    accepted: dict[str, Any] = {}
    problems: dict[str, list[str]] = {}
    for attempt in (1, 2):
        try:
            raw = await asyncio.wait_for(
                llm.with_structured_output(schema).ainvoke(messages, config=trace_config(prompt, attempt, trace_id)),
                timeout=settings.llm_timeout_seconds)
            ok, bad = check(_coerce(schema, raw))
        except asyncio.TimeoutError:
            detail = "LLM call timed out"
        except (ValidationError, ValueError) as e:
            detail = "LLM output did not match the expected schema"
            logger.info("Recommender LLM output invalid: %s", type(e).__name__)
        except Exception as e:  # provider or network errors
            logger.warning("Recommender LLM call failed: %s: %.300s", type(e).__name__, e)
            detail = f"LLM call failed ({type(e).__name__})"
        else:
            # A later attempt only fills items the earlier one got wrong.
            accepted = {**ok, **accepted}
            problems = {k: v for k, v in bad.items() if k not in accepted}
            if not problems:
                break
            logger.info("Recommender LLM text rejected (attempt %d): %s", attempt, problems)
            messages = [*messages, ("human", _feedback(problems))]
            continue
        # Malformed tool-call JSON is often a one-off, so try once more; a timeout is not retried.
        if attempt == 1 and detail != "LLM call timed out":
            continue
        if not accepted:
            return WriteResult(deterministic_status(f"{detail}; rule-based text provided instead.", settings, attempted=True))
        break

    if not accepted:
        first = next(iter(sorted(problems.items())), ("", ["no usable text"]))
        return WriteResult(deterministic_status(
            f"LLM text failed the guardrail twice ({first[0]}: {first[1][0]}); rule-based text provided instead.",
            settings, attempted=True))
    kept = [i for i in ids if i not in accepted]
    detail = "Written by the LLM from engine-computed facts and checked by the guardrail. Rankings, stances and numbers come from the engine."
    if kept:
        detail += f" Rule-based text kept for {', '.join(kept)} after the guardrail rejected the LLM text."
    return WriteResult(ExplanationStatus(source="LLM", llm_attempted=True, llm_succeeded=True, model=settings.llm_model,
                                         detail=detail), accepted)
